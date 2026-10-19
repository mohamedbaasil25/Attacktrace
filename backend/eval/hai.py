"""HAI evaluation on held-out test files: detection vs the baseline, and process-level localization.

HAI labels say *which process* (P1-P3) an attack hits, not which component, so localization is
scored per process: is the top-ranked node's process one that was actually attacked?
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.data.hai import PROCESSES, SAMPLE_HZ, HaiFile, load_hai, process_of
from app.detect.baseline import SIGMA, BaselineDetector
from app.detect.detector import aggregate, alert_mask, rising_edges
from app.detect.hai_pipeline import (
    TOP_K,
    WINDOW,
    HaiLoaded,
    load_hai_baseline,
    load_hai_detector,
    split_tests,
)
from app.localize import Weights
from app.localize.incident import FORWARD_S, LOOKBACK_S
from app.localize.locator import localize

F64 = NDArray[np.float64]
DT = 1.0 / SAMPLE_HZ


@dataclass(frozen=True)
class Scored:
    file: HaiFile
    scores: F64
    errors: F64
    alert: NDArray[np.bool_]


def score_file(loaded: HaiLoaded, f: HaiFile) -> Scored:
    scores = loaded.detector.score_run(f.x)
    errors = loaded.detector.errors(f.x)
    return Scored(f, scores, errors, alert_mask(aggregate(scores, TOP_K), loaded.threshold))


def _prf(alert: NDArray[np.bool_], y: NDArray[np.int8]) -> dict[str, float]:
    ok = y >= 0
    a, lab = alert[ok], y[ok]
    tp, fp, fn = (
        int(np.sum(a & (lab == 1))),
        int(np.sum(a & (lab == 0))),
        int(np.sum(~a & (lab == 1))),
    )
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-12)}


def evaluate_detector(name: str, f: HaiFile, alert: NDArray[np.bool_]) -> dict[str, object]:
    y = f.labels()
    windows = f.windows()
    delays, hit = [], []
    for s, e in windows:
        idx = np.flatnonzero(alert[s:e])
        hit.append(idx.size > 0)
        if idx.size:
            delays.append(float(idx[0]) / SAMPLE_HZ)
    clean_hours = float(np.sum(y == 0)) / SAMPLE_HZ / 3600.0
    false_edges = sum(1 for i in rising_edges(alert) if y[i] == 0)
    adjusted = alert.copy()
    for s, e in windows:  # point-adjust: one alert inside an attack credits the whole attack
        if alert[s:e].any():
            adjusted[s:e] = True
    return {
        "detector": name,
        **_prf(alert, y),
        "f1_point_adjusted": _prf(adjusted, y)["f1"],
        "false_alarm_per_hour": false_edges / max(clean_hours, 1e-9),
        "windows_detected": float(np.mean(hit)),
        "n_windows": len(windows),
        "mean_detection_delay_s": float(np.mean(delays)) if delays else None,
    }


def truth_processes(f: HaiFile, start: int, end: int) -> set[str]:
    flags = f.by_process[start:end].max(axis=0)
    return {p for p, v in zip(PROCESSES[:3], flags, strict=True) if v}


def _first_alert(alert: NDArray[np.bool_], start: int, end: int) -> int | None:
    idx = np.flatnonzero(alert[start:end])
    return start + int(idx[0]) if idx.size else None


def _span(alert_idx: int, n: int) -> tuple[int, int]:
    return max(0, alert_idx - round(LOOKBACK_S / DT)), min(n, alert_idx + round(FORWARD_S / DT) + 1)


def rank_nodes(loaded: HaiLoaded, s: Scored, alert_idx: int, weights: Weights) -> list[str]:
    lo, hi = _span(alert_idx, len(s.scores))
    cands = localize(
        s.scores[lo:hi],
        loaded.node_thr,
        loaded.graph,
        weights,
        names=loaded.features,
        errors=s.errors[lo:hi],
        types=loaded.types,
    )
    return [c.id for c in cands]


def baseline_rank_nodes(base: BaselineDetector, f: HaiFile, alert_idx: int) -> list[str]:
    lo, hi = _span(alert_idx, len(f.x))
    z = base.zscores(f.x[lo:hi])
    breach = z > SIGMA
    first = np.where(breach.any(axis=0), breach.argmax(axis=0), len(z))
    order = sorted(range(z.shape[1]), key=lambda i: (first[i], -z[:, i].max()))
    return [base.names[i] for i in order]


def process_scores(ranked: list[str], truth: set[str]) -> tuple[bool, bool]:
    procs = [process_of(n) for n in ranked]
    return procs[0] in truth, bool(truth & set(procs[:3]))


def evaluate_localization(
    loaded: HaiLoaded, scored: Scored, weights: Weights, base: BaselineDetector | None = None
) -> dict[str, object]:
    """Process-level Top-1/Top-3. A miss (no alert inside the attack) counts as wrong in the
    headline numbers; `*_given_detected` scores only attacks that raised an alert, next to the
    "always answer the most-attacked process" reference on the same attacks."""
    f = scored.file
    base_alert = rising_edges(base.alert(f.x)) if base else None
    rows: list[tuple[bool, bool] | None] = []  # None = never alerted
    base_rows: list[tuple[bool, bool]] = []
    truths: list[set[str]] = []
    for s, e in f.windows():
        truth = truth_processes(f, s, e)
        if not truth:
            continue
        truths.append(truth)
        a = _first_alert(scored.alert, s, e)
        rows.append(
            process_scores(rank_nodes(loaded, scored, a, weights), truth) if a is not None else None
        )
        if base is not None and base_alert is not None:
            inside = base_alert[(base_alert >= s) & (base_alert < e)]
            base_rows.append(
                process_scores(baseline_rank_nodes(base, f, int(inside[0])), truth)
                if inside.size
                else (False, False)
            )
    hit = [r if r is not None else (False, False) for r in rows]
    det = [(r, t) for r, t in zip(rows, truths, strict=True) if r is not None]
    majority = Counter(p for t in truths for p in t).most_common(1)[0][0]
    det_majority = Counter(p for _, t in det for p in t).most_common(1)[0][0] if det else majority
    out: dict[str, object] = {
        "process_top1": float(np.mean([a for a, _ in hit])),
        "process_top3": float(np.mean([b for _, b in hit])),
        "always_majority_process": float(np.mean([majority in t for t in truths])),
        "majority_process": majority,
        "n_windows": len(rows),
        "n_detected": len(det),
        "process_top1_given_detected": float(np.mean([r[0] for r, _ in det])) if det else None,
        "always_majority_given_detected": float(np.mean([det_majority in t for _, t in det]))
        if det
        else None,
        "weights": {
            "deviation": weights.deviation,
            "onset": weights.onset,
            "causal": weights.causal,
        },
    }
    if base_rows:
        out["baseline"] = {
            "process_top1": float(np.mean([a for a, _ in base_rows])),
            "process_top3": float(np.mean([b for _, b in base_rows])),
        }
    return out


def tune_weights(
    loaded: HaiLoaded, tuned: Scored, step: float = 0.1, floor: float = 0.2
) -> Weights:
    """Same grid as SIM (each weight >= floor), scored on the tuning file's attacks."""
    k, lo = round(1 / step), round(floor / step)
    best, best_w = -1.0, Weights()
    for a in range(lo, k - 2 * lo + 1):
        for b in range(lo, k - a - lo + 1):
            w = Weights(a * step, b * step, (k - a - b) * step)
            r = evaluate_localization(loaded, tuned, w)
            obj = float(r["process_top1"]) + float(r["process_top3"])  # type: ignore[arg-type]
            if obj > best:
                best, best_w = obj, w
    return best_w


def run_hai_eval(models_dir: Path, hai_dir: Path) -> dict[str, object]:
    data = load_hai(hai_dir)
    tune, held = split_tests(data)
    loaded, base = load_hai_detector(models_dir), load_hai_baseline(models_dir)
    weights = tune_weights(loaded, score_file(loaded, tune))
    detection: dict[str, list[dict[str, object]]] = {"attacktrace": [], "baseline": []}
    loc: list[dict[str, object]] = []
    for f in held:
        sc = score_file(loaded, f)
        detection["attacktrace"].append(evaluate_detector("forecaster", f, sc.alert))
        detection["baseline"].append(evaluate_detector("iforest+3sigma", f, base.alert(f.x)))
        loc.append(evaluate_localization(loaded, sc, weights, base))
    # one held-out file is the norm; with several, report the first and list the files
    return {
        "files": [f.name for f in held],
        "tuned_on": tune.name,
        "active_model": loaded.kind,
        "attacktrace": detection["attacktrace"][0],
        "baseline": detection["baseline"][0],
        "localization": loc[0],
        "top_k": TOP_K,
        "window": WINDOW,
    }
