"""`make eval` entrypoint: trains detectors if missing, evaluates, writes reports/metrics.json."""

import json
import logging
import sys
from typing import Any

from app.config import Settings, get_settings
from app.data.hai import hai_paths
from app.detect.hai_pipeline import hai_models_ready, train_hai
from app.detect.pipeline import load_baseline, load_detector, train_all
from app.graph import load_graph
from app.localize import Weights
from eval.ambiguity import rows as ambiguity_rows
from eval.ambiguity import summarize, tuning_rows
from eval.detection import run_detection
from eval.hai import run_hai_eval
from eval.isolation import run_isolation
from eval.localization import (
    evaluate_baseline_localization,
    evaluate_localization,
    score_runs,
    test_runs,
)


def write_metrics(s: Settings) -> dict[str, Any]:
    """Train if needed, evaluate on held-out SIM attacks, write and return reports/metrics.json."""
    if not (s.models_dir / "detector.json").exists():
        train_all(s.models_dir)
    meta = json.loads((s.models_dir / "detector.json").read_text())
    loaded = load_detector(s.models_dir)
    detection = run_detection(loaded.detector, loaded.threshold, load_baseline(s.models_dir))
    detection["active_model"] = meta["active"]
    detection["validation"] = {
        k: {"f1": v["val_f1"], "mse": v["val_mse"]} for k, v in meta["models"].items()
    }
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    path = s.reports_dir / "metrics.json"
    metrics = json.loads(path.read_text()) if path.exists() else {}
    metrics["detection"] = detection
    w = Weights(s.w_deviation, s.w_onset, s.w_causal)
    graph = load_graph(s.models_dir / "graph.json")
    runs = test_runs()
    scored = score_runs(loaded, runs)
    loc = evaluate_localization(loaded, graph, scored, w)
    loc["baseline"] = evaluate_baseline_localization(load_baseline(s.models_dir), runs)
    metrics["localization"] = loc
    # Confidence gate: margin tuned on validation + tuning attacks, scored once on the test attacks.
    amb = summarize(ambiguity_rows(loaded, graph, scored, w), s.gate_margin)
    amb["tuning"] = summarize(tuning_rows(loaded, graph, w), s.gate_margin)
    metrics["ambiguity"] = amb
    metrics["isolation"] = run_isolation(loaded, load_baseline(s.models_dir), graph, s)
    if hai_paths(s.hai_dir):
        try:  # the SIM results above stand even if the optional HAI data cannot be read
            if not hai_models_ready(s.models_dir):
                train_hai(s.models_dir, s.hai_dir)
            metrics["hai"] = run_hai_eval(s.models_dir, s.hai_dir)
        except Exception:
            logging.getLogger("attacktrace").exception("HAI evaluation skipped")
    path.write_text(json.dumps(metrics, indent=1))
    metrics["_path"] = str(path)
    return metrics


def main() -> int:
    s = get_settings()
    metrics = write_metrics(s)
    path = metrics.pop("_path")
    detection, loc = metrics["detection"], metrics["localization"]
    meta = json.loads((s.models_dir / "detector.json").read_text())
    at, bl = detection["attacktrace"], detection["baseline"]
    assert isinstance(at, dict) and isinstance(bl, dict)
    print(f"active={meta['active']}  wrote {path}")
    for name, m in (("attacktrace", at), ("baseline", bl)):
        print(
            f"{name:12s} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} "
            f"FA/h={m['false_alarm_per_hour']:.1f}"
        )
    print(
        f"localization Top-1={loc['top1']:.3f} Top-3={loc['top3']:.3f} "
        f"time-to-localize={loc['mean_time_to_localize_s']:.1f}s"
    )
    amb, iso = metrics["ambiguity"], metrics["isolation"]
    print(
        f"ambiguity    margin={amb['gate_margin']} rate={amb['ambiguous_rate']:.2f} "
        f"Top-1 (not ambiguous)={amb['top1_non_ambiguous']:.3f} "
        f"Top-3 (ambiguous)={amb['top3_ambiguous']:.3f}"
    )
    print(
        f"isolation    Top-1 click contained "
        f"{iso['isolate_top1']['contained']}/{iso['n_detected']}, "
        f"true origin {iso['isolate_true_origin']['contained']}/{iso['n_detected']}, "
        f"wrong node {iso['isolate_wrong_node']['contained']}/{iso['isolate_wrong_node']['n']}"
    )
    base_loc = loc["baseline"]
    assert isinstance(base_loc, dict)
    print(f"baseline     Top-1={base_loc['top1']:.3f} Top-3={base_loc['top3']:.3f}")
    hai = metrics.get("hai")
    if hai:
        a, b, hl = hai["attacktrace"], hai["baseline"], hai["localization"]
        print(f"HAI ({hai['files'][0]}, tuned on {hai['tuned_on']}, {hai['active_model']})")
        print(
            f"  attacktrace P={a['precision']:.3f} R={a['recall']:.3f} F1={a['f1']:.3f} "
            f"(point-adjusted {a['f1_point_adjusted']:.3f}) FA/h={a['false_alarm_per_hour']:.2f} "
            f"windows {a['windows_detected']:.0%}"
        )
        print(f"  baseline    F1={b['f1']:.3f} FA/h={b['false_alarm_per_hour']:.2f}")
        print(
            f"  process Top-1={hl['process_top1']:.3f} (given detected "
            f"{hl['process_top1_given_detected']:.3f} vs always-{hl['majority_process']} "
            f"{hl['always_majority_given_detected']:.3f})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
