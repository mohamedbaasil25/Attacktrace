"""Phase 16 C3: a fairer HAI baseline -- tune the 3-sigma baseline's own alarm threshold on
`test2` (the same tuning file AttackTrace's own detector threshold is tuned on, same
`best_threshold`-style procedure: maximize pooled sample-level strict F1 on the tuning file), then
report it held-out on `test1`. The originally-committed baseline comparison used a fixed SIGMA=3.0
(`app/detect/baseline.py`) never tuned for HAI at all -- it was carried over from the SIM baseline
unchanged, which is why it's "permanently in alarm" on HAI (strict F1 0.077, precision 0.040).

Also runs the exact paired comparison C3 asks for: AttackTrace's process-Top-1 vs the "always
answer the majority process" guess, over the SAME detected attacks (not just the two marginal
rates), with an exact sign-test p-value and the plain-language reading that a one-attack
difference at this sample size is not evidence.

Read-only: never changes `app/detect/baseline.py`'s SIGMA or the committed, saved
`models/hai/baseline.joblib` -- this sigma sweep is local to this script and recomputes the breach
mask from the already-fitted detector's own `.norm`/`._forest`, nothing is retrained.
"""

from collections import Counter
from math import comb

import numpy as np
from numpy.typing import NDArray

from app.config import get_settings
from app.data.hai import load_hai
from app.detect.baseline import BaselineDetector
from app.detect.hai_pipeline import load_hai_baseline, load_hai_detector, split_tests
from app.localize import Weights
from eval.analysis._util import merge_write_final
from eval.hai import (
    _first_alert,
    _prf,
    evaluate_detector,
    process_scores,
    rank_nodes,
    score_file,
    truth_processes,
)

F64 = NDArray[np.float64]
# A narrow grid (0.5-6.0, the range that would matter on well-behaved SIM-style data) turned out
# to find NOTHING: diagnosed mid-analysis that 1-2 real HAI channels (P1_PCV02Z max|z|=2126,
# P2_SIT01 max|z|=542) have near-zero clean-period variance, so tiny absolute deviations alone
# produce z-scores in the hundreds/thousands -- the 3-sigma breach rule alarms on essentially
# every sample up to sigma~500 regardless of any real attack, purely from those channels' own
# noise floor. The grid below is wide enough to actually cross that regime.
SIGMA_GRID = np.concatenate(
    [np.arange(0.5, 6.25, 0.25), np.array([10, 20, 50, 100, 200, 500, 1000, 1500, 2000, 2500])]
)


def _alert_with_sigma(base: BaselineDetector, x: F64, sigma: float) -> NDArray[np.bool_]:
    """Same two-part rule as `BaselineDetector.alert()` (3-sigma breach OR isolation-forest
    outlier), with the sigma threshold as a free parameter instead of the hardcoded module
    constant. Reuses the already-fitted `.norm` and `._forest` -- nothing is refit."""
    assert base.norm is not None
    z = base.norm.apply(x)
    breach = (np.abs(z) > sigma).any(axis=1)
    outlier = base._forest.predict(z) == -1  # read-only reuse of the already-fitted forest
    return np.asarray(breach | outlier)


def _strict_f1(alert: NDArray[np.bool_], y: NDArray[np.int8]) -> float:
    f1: float = _prf(alert, y)["f1"]
    return f1


def _tune_sigma(base: BaselineDetector, x: F64, y: NDArray[np.int8]) -> tuple[float, float]:
    """Sweep sigma, maximizing pooled strict F1 on the tuning file -- same objective
    `best_threshold` uses for AttackTrace's own detector threshold."""
    best_sigma, best_f1 = float(SIGMA_GRID[0]), -1.0
    for sigma in SIGMA_GRID:
        f1 = _strict_f1(_alert_with_sigma(base, x, float(sigma)), y)
        if f1 > best_f1:
            best_sigma, best_f1 = float(sigma), f1
    return best_sigma, best_f1


def _exact_sign_test_two_sided(k: int, n: int) -> float:
    """Exact two-sided sign-test p-value for n discordant pairs, k won by one side. Used instead
    of McNemar's chi-square approximation, which is unreliable at n<25."""
    if n == 0:
        return 1.0
    larger = max(k, n - k)
    tail = sum(comb(n, i) for i in range(larger, n + 1)) / (2**n)
    return float(min(1.0, 2 * tail))


def _detected_process_correctness(
    loaded: object, sc: object, held: object, weights: Weights
) -> tuple[list[bool], list[bool], str]:
    """Walks the held-out file's labeled attack windows once, returning (per-attack AttackTrace
    Top-1 correct, per-attack majority-guess correct) for exactly the detected attacks, paired in
    the same order -- needed for an exact paired test, which the committed `evaluate_localization`
    (aggregate-only) doesn't expose."""
    truths: list[set[str]] = []
    detected_truths: list[set[str]] = []
    attacktrace_correct: list[bool] = []
    for s, e in held.windows():  # type: ignore[attr-defined]
        truth = truth_processes(held, s, e)  # type: ignore[arg-type]
        if not truth:
            continue
        truths.append(truth)
        a = _first_alert(sc.alert, s, e)  # type: ignore[attr-defined]
        if a is None:
            continue
        ranked = rank_nodes(loaded, sc, a, weights)  # type: ignore[arg-type]
        top1, _ = process_scores(ranked, truth)
        detected_truths.append(truth)
        attacktrace_correct.append(top1)
    majority = Counter(p for t in truths for p in t).most_common(1)[0][0]
    majority_correct = [majority in t for t in detected_truths]
    return attacktrace_correct, majority_correct, majority


def analyze() -> dict[str, object]:
    settings = get_settings()
    data = load_hai(settings.hai_dir)
    tune_file, held_files = split_tests(data)
    held = held_files[0]
    base = load_hai_baseline(settings.models_dir)
    loaded = load_hai_detector(settings.models_dir)
    weights = Weights(settings.w_deviation, settings.w_onset, settings.w_causal)

    # --- diagnostic: which channel(s) drive the "permanently in alarm" behavior ---
    assert base.norm is not None
    z_tune = base.norm.apply(tune_file.x)
    max_abs_z = np.abs(z_tune).max(axis=0)
    top_idx = np.argsort(-max_abs_z)[:5]
    noisy_channels = [
        {"node": base.names[i], "max_abs_z": round(float(max_abs_z[i]), 1)} for i in top_idx
    ]
    breach_rate_by_sigma = {
        str(s): round(float((np.abs(z_tune) > s).any(axis=1).mean()), 5)
        for s in [3.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 2000.0]
    }

    # --- tune the baseline's own sigma on test2, apply held-out on test1 ---
    tune_sigma, tune_f1 = _tune_sigma(base, tune_file.x, tune_file.labels())
    tuned_detection = evaluate_detector(
        "iforest+tuned_sigma", held, _alert_with_sigma(base, held.x, tune_sigma)
    )
    committed_detection = evaluate_detector("iforest+3sigma (shipped)", held, base.alert(held.x))

    # --- paired process-Top-1 comparison, AttackTrace vs majority-guess, same detected attacks ---
    sc = score_file(loaded, held)
    at_correct, maj_correct, majority = _detected_process_correctness(loaded, sc, held, weights)
    n = len(at_correct)
    at_only = sum(a and not m for a, m in zip(at_correct, maj_correct, strict=True))
    maj_only = sum(m and not a for a, m in zip(at_correct, maj_correct, strict=True))
    both = sum(a and m for a, m in zip(at_correct, maj_correct, strict=True))
    neither = sum(not a and not m for a, m in zip(at_correct, maj_correct, strict=True))
    n_discordant = at_only + maj_only
    p_value = _exact_sign_test_two_sided(at_only, n_discordant)

    tuned_f1 = tuned_detection["f1"]
    shipped_f1 = committed_detection["f1"]
    assert isinstance(tuned_f1, float) and isinstance(shipped_f1, float)

    return {
        "diagnostic_why_permanently_in_alarm": {
            "noisiest_channels_by_max_abs_z_on_tuning_file": noisy_channels,
            "breach_rate_by_sigma_on_tuning_file": breach_rate_by_sigma,
            "explanation": (
                "The per-node 3-sigma breach rule ORs across all nodes, so ONE pathological "
                f"channel is enough to alarm on nearly every sample: {noisy_channels[0]['node']} "
                f"alone reaches |z|={noisy_channels[0]['max_abs_z']} (hundreds to thousands of "
                "clean-period standard deviations) on real HAI data, where the simulator's clean "
                "channels never approach that. This isn't a sigma-tuning problem: breach rate "
                "stays near 100% from sigma=3 through roughly sigma=500 (see the table above) "
                "purely from this channel's own noise floor, before any attack is considered."
            ),
        },
        "baseline_threshold_tuning": {
            "tuned_on_file": tune_file.name,
            "held_out_file": held.name,
            "sigma_grid": [round(float(s), 2) for s in SIGMA_GRID],
            "tuned_sigma": tune_sigma,
            "tuning_file_f1_at_tuned_sigma": tune_f1,
            "shipped_sigma": 3.0,
            "held_out_detection_tuned_sigma": tuned_detection,
            "held_out_detection_shipped_sigma_3_0": committed_detection,
            "verdict": (
                f"Tuning the baseline's own sigma on test2 across a wide grid (up to "
                f"{float(SIGMA_GRID[-1]):.0f}, well past where it matters on SIM-style data) "
                f"picks sigma={tune_sigma:.2f}, not the shipped 3.0. Held-out strict F1: "
                f"{tuned_f1:.3f} (tuned) vs {shipped_f1:.3f} (shipped 3-sigma, = the committed "
                "metrics.json figure). "
                + (
                    "The tuned baseline is still far below AttackTrace's own HAI F1 (0.428) -- "
                    "not close competition even under its best own threshold, and the "
                    "noisy-channel diagnostic above explains why sigma tuning alone can't fix "
                    "it: the per-node OR rule needs a per-channel threshold or a dropped/clipped "
                    "noisy channel, not a single global sigma."
                    if tuned_f1 < 0.428
                    else "The tuned baseline closes meaningfully on AttackTrace's own HAI F1 "
                    "(0.428) -- re-examine the headline comparison if citing it."
                )
            ),
        },
        "paired_process_top1_comparison": {
            "n_detected_attacks": n,
            "attacktrace_correct": sum(at_correct),
            "majority_guess_correct": sum(maj_correct),
            "both_correct": both,
            "attacktrace_only_correct": at_only,
            "majority_only_correct": maj_only,
            "neither_correct": neither,
            "n_discordant_pairs": n_discordant,
            "exact_two_sided_p_value": p_value,
            "majority_process": majority,
            "plain_language": (
                f"Of {n} detected attacks: both correct {both}, both wrong {neither}, only "
                f"AttackTrace correct {at_only}, only the majority guess correct {maj_only} "
                f"({n_discordant} discordant pairs). Exact two-sided sign test: p={p_value:.3f} -- "
                + (
                    "not statistically distinguishable from chance at any conventional "
                    "threshold (p > 0.05): with this few detected attacks and this few "
                    "discordant pairs, the observed difference is not evidence AttackTrace's "
                    "process-level ranking beats a constant guess on this dataset."
                    if p_value > 0.05
                    else "statistically distinguishable from chance (p <= 0.05), though still "
                    "a small-sample result worth reading cautiously."
                )
            ),
        },
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("c3_hai_fairer_baseline", result)
    bt = result["baseline_threshold_tuning"]
    pc = result["paired_process_top1_comparison"]
    assert isinstance(bt, dict) and isinstance(pc, dict)
    tuned_f1 = bt["held_out_detection_tuned_sigma"]["f1"]
    shipped_f1 = bt["held_out_detection_shipped_sigma_3_0"]["f1"]
    print(f"wrote {out}")
    print(
        f"  tuned sigma={bt['tuned_sigma']:.2f} held F1={tuned_f1:.3f} "
        f"vs shipped 3.0 F1={shipped_f1:.3f}"
    )
    print(
        f"  paired n={pc['n_detected_attacks']} AT={pc['attacktrace_correct']} "
        f"majority={pc['majority_guess_correct']} p={pc['exact_two_sided_p_value']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
