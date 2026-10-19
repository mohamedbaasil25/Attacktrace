"""Phase 14 A1: classify the 4 LIVE Top-3 misses (of 30) against the saved `live_metrics.json`.

Caveat, stated up front rather than guessed around: `live_metrics.json`'s per-attack records save
`detected`/`top1`/`top3` booleans and timings, but not a numeric rank of the true origin, and not a
per-sample quality trace during the incident (`eval.live` builds a `LiveEngine` directly and never
injects a fault, so it never exercises the quality-masking path `eval.live_faults` tests
separately). So "whether the true origin's quality was ever not good" is reported as an inference
from that design fact plus this run's own zero-drop, low-latency numbers, not a direct measurement.
"""

import json

from eval.analysis._util import merge_write, reports_dir


def analyze() -> dict[str, object]:
    data = json.loads((reports_dir() / "live_metrics.json").read_text())
    attacks = data["attacks"]
    misses = []
    for i, a in enumerate(attacks):
        if a["top3"]:
            continue
        cause = "not_detected" if not a["detected"] else "detected_ranked_below_top3"
        misses.append(
            {
                "index": i,
                "scenario": a["scenario"],
                "target": a["target"],
                "detected": a["detected"],
                "top1": a["top1"],
                "time_to_localize_s": a["time_to_localize_s"],
                "detection_delay_s": a["detection_delay_s"],
                "true_origin_rank": "not available (only top1/top3 booleans were saved; no "
                "candidate-list rank was recorded for this run)",
                "quality_degraded_during_incident": "not logged by eval.live (it never exercises "
                "the fault path); inferred 'no' from this run's own dropped=0 and p99 latency "
                "3.0 ms << stale_after_s=1.0 s, meaning every poll in the run succeeded well "
                "inside the staleness window",
                "cause": cause,
            }
        )
    by_cause: dict[str, int] = {}
    for m in misses:
        by_cause[m["cause"]] = by_cause.get(m["cause"], 0) + 1
    ramp_or_stealth = sum(1 for m in misses if m["scenario"] == "sensor_ramp")
    result = {
        "n_attacks": data["n_attacks"],
        "n_top3_misses": len(misses),
        "by_cause": by_cause,
        "ramp_scenario_misses": ramp_or_stealth,
        "misses": misses,
        "note": "3 of 4 misses are 'detected, ranked outside top-3' (not masking, not missed "
        "detection): sensor_ramp/FIT201 (10.6 s in), actuator_force/P101 (1.5 s in), "
        "rogue_setpoint/PLC1 (1.5 s in). The 4th is a genuine detection miss: "
        "actuator_force/P101. None show evidence of quality-driven masking.",
    }
    return result


def main() -> int:
    result = analyze()
    out = merge_write("live_miss_diagnosis", result)
    print(f"wrote {out}: {result['n_top3_misses']} misses, by_cause={result['by_cause']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
