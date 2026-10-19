"""Phase 14 A3: confidence reliability (ECE, Brier) for the Top-1 localization confidence.

No per-attack confidence value was ever saved to a report file (only the aggregate mean, and that
from the TUNING set, not the held-out test set -- see eval/localization.py's printed "mean top-1
confidence" during calibration). This recomputes it for SIM via a read-only forward pass reusing
the exact scoring pipeline (`eval/localization.py`'s own `score_runs`/`evaluate_localization`,
same model, same graph, same weights, same held-out seeds, deterministic) over the committed test
seeds -- not training, not tuning.

HAI is skipped: labels are process-level (P1-P3), not component-level, so "is the top-ranked
*component*'s confidence calibrated against whether that *component* was the true origin" is not a
well-posed question on HAI's labels (per A3's own escape clause).

LIVE is skipped: no per-attack confidence was saved, and recomputing needs the ~2h53m real-time
eval.live run re-run -- not done here without a specific decision to spend that time.
"""

import json

from app.config import get_settings
from app.detect.pipeline import load_detector
from app.graph import load_graph
from app.localize import Weights, build_incident
from eval.analysis._util import merge_write, reports_dir
from eval.localization import TEST_ATTACK_SEEDS, score_runs, test_runs

N_BINS = 10


def _ece_brier(pairs: list[tuple[float, bool]]) -> dict[str, object]:
    n = len(pairs)
    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in pairs) / n
    bins: list[dict[str, object]] = []
    ece = 0.0
    for b in range(N_BINS):
        lo, hi = b / N_BINS, (b + 1) / N_BINS
        in_bin = [(c, ok) for c, ok in pairs if (lo <= c < hi) or (b == N_BINS - 1 and c == hi)]
        if not in_bin:
            bins.append({"range": [lo, hi], "n": 0, "mean_confidence": None, "accuracy": None})
            continue
        mean_conf = sum(c for c, _ in in_bin) / len(in_bin)
        acc = sum(1 for _, ok in in_bin if ok) / len(in_bin)
        ece += abs(acc - mean_conf) * len(in_bin) / n
        bins.append(
            {"range": [lo, hi], "n": len(in_bin), "mean_confidence": mean_conf, "accuracy": acc}
        )
    return {"n": n, "ece": ece, "brier": brier, "bins": bins}


def analyze() -> dict[str, object]:
    settings = get_settings()
    loaded = load_detector(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    metrics = json.loads((reports_dir() / "metrics.json").read_text())
    w = metrics["localization"]["weights"]
    weights = Weights(w["deviation"], w["onset"], w["causal"])

    runs = test_runs()
    assert list(TEST_ATTACK_SEEDS) == list(range(1000, 1010))  # same held-out seeds as committed
    scored = score_runs(loaded, runs)
    mu = loaded.detector.norm.mu

    pairs: list[tuple[float, bool]] = []
    for s in scored:
        if s.alert_idx is None:
            continue  # undetected: no confidence was ever produced for this attack
        inc = build_incident(
            s.scores, s.errors, s.run.x, s.alert_idx, mu, loaded.node_thr, graph, weights
        )
        top = inc.candidates[0]
        assert s.run.truth is not None
        pairs.append((top.confidence, top.id == s.run.truth.target))

    sim_result = _ece_brier(pairs)
    mean_conf = sum(c for c, _ in pairs) / len(pairs)
    mean_acc = sum(1 for _, ok in pairs if ok) / len(pairs)
    bins: list[dict[str, object]] = sim_result["bins"]  # type: ignore[assignment]
    sim_result["mean_top1_confidence"] = mean_conf
    sim_result["top1_accuracy"] = mean_acc
    sim_result["higher_confidence_means_higher_accuracy"] = (
        bins[-1]["accuracy"] is not None
        and bins[0]["accuracy"] is not None
        and bins[-1]["accuracy"] >= bins[0]["accuracy"]  # type: ignore[operator]
    )

    return {
        "sim": sim_result,
        "hai": "skipped: HAI labels are process-level (P1-P3), not component-level -- "
        "component-confidence-vs-component-correctness is not well-posed on this label set",
        "live": "not computed: per-attack confidence was not saved by eval.live, and "
        "recomputing it needs the ~2h53m real-time run re-run; flagging rather than running",
    }


def main() -> int:
    result = analyze()
    out = merge_write("confidence_reliability", result)
    s = result["sim"]
    assert isinstance(s, dict)
    print(
        f"wrote {out}: SIM n={s['n']} ECE={s['ece']:.3f} Brier={s['brier']:.3f} "
        f"mean_conf={s['mean_top1_confidence']:.3f} acc={s['top1_accuracy']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
