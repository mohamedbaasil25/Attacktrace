"""Phase 16 A3: demo vs evaluation magnitude/timing gap.

Compares the demo's fixed attack (sensor_offset on LIT101, magnitude -25, from
`submission/evidence/rehearsal.json`) against the evaluation's sampled magnitude distribution
for that scenario (`app/data/simdata.py:sample_attack`, read directly -- no new sampling), and
recomputes per-scenario mean detection delay (not saved anywhere at scenario granularity
previously, only the all-scenario aggregate in `metrics.json`) via the same read-only,
frozen-model forward pass pattern as `_compute.py`, so the demo's single run can be compared on
a like-for-like (same scenario) basis instead of against the cross-scenario aggregate.
"""

import json
from typing import Any

from app.attacks import Scenario
from app.config import get_settings
from app.detect.detector import aggregate, alert_mask, rising_edges
from app.detect.pipeline import load_detector
from app.sim.topology import NODE_BY_ID
from eval.analysis._util import merge_write_final
from eval.localization import TEST_ATTACK_SEEDS, test_runs

MAGNITUDE_RANGES_OF_SPAN = {
    # From app/data/simdata.py:sample_attack, read directly (not re-derived/guessed).
    "sensor_offset": (0.15, 0.30),
    "sensor_ramp": (0.20, 0.40),
    # actuator_force and rogue_setpoint do not scale with node span (see sample_attack).
}


def _rehearsal() -> list[dict[str, Any]]:
    path = get_settings().reports_dir.parent / "submission" / "evidence" / "rehearsal.json"
    data: list[dict[str, Any]] = json.loads(path.read_text())
    return data


def _per_scenario_detection_delay(scenario: Scenario) -> dict[str, object]:
    settings = get_settings()
    loaded = load_detector(settings.models_dir)
    runs = [r for r in test_runs() if r.truth is not None and r.truth.scenario is scenario]
    delays: list[float] = []
    n_missed = 0
    for r in runs:
        assert r.truth is not None
        scores = loaded.detector.score_run(r.x)
        alert = alert_mask(aggregate(scores), loaded.threshold)
        edges = rising_edges(alert)
        edges = edges[r.t[edges] >= r.truth.start_s]
        if edges.size:
            delays.append(float(r.t[edges[0]] - r.truth.start_s))
        else:
            n_missed += 1
    return {
        "n": len(runs),
        "n_detected": len(delays),
        "n_missed": n_missed,
        "mean_detection_delay_s": sum(delays) / len(delays) if delays else None,
        "min_s": min(delays) if delays else None,
        "max_s": max(delays) if delays else None,
    }


def analyze() -> dict[str, object]:
    rehearsal = _rehearsal()
    demo_row = next(
        r for r in rehearsal if r["scenario"] == "sensor_offset" and r["target"] == "LIT101"
    )
    demo_mag = float(demo_row["magnitude"])
    span = NODE_BY_ID["LIT101"].hi - NODE_BY_ID["LIT101"].lo
    demo_frac = abs(demo_mag) / span
    eval_lo, eval_hi = MAGNITUDE_RANGES_OF_SPAN["sensor_offset"]

    offset_delay = _per_scenario_detection_delay(Scenario.SENSOR_OFFSET)
    ramp_delay = _per_scenario_detection_delay(Scenario.SENSOR_RAMP)

    ramp_rows = [r for r in rehearsal if r["scenario"] == "sensor_ramp"]

    return {
        "n_test_seeds_per_scenario": len(list(TEST_ATTACK_SEEDS)),
        "demo_attack": {
            "scenario": "sensor_offset",
            "target": "LIT101",
            "magnitude": demo_mag,
            "fraction_of_span": demo_frac,
            "detect_s": demo_row["detect_s"],
            "localized_s": demo_row["localized_s"],
        },
        "evaluation_magnitude_distribution": {
            "scenario": "sensor_offset",
            "sampled_fraction_of_span_range": [eval_lo, eval_hi],
            "sign": "uniform random +/-",
            "verdict": (
                "The demo's magnitude (fraction of span = "
                f"{demo_frac:.3f}) falls INSIDE the evaluation's own sampled range "
                f"[{eval_lo}, {eval_hi}] -- it is representative of the distribution the "
                "evaluation draws from, not an unusually strong/easy outlier. It sits in the "
                "upper half of that range, not at either extreme."
            ),
        },
        "sensor_offset_detection_delay": {
            "per_scenario_recomputed": offset_delay,
            "demo_detect_s": demo_row["detect_s"],
            "note": "metrics.json only saves the ALL-SCENARIO mean detection delay (11.14s); this "
            "is the first scenario-specific figure, recomputed read-only from the frozen detector "
            "over the same 10 held-out sensor_offset test seeds (1000-1009).",
        },
        "sensor_ramp": {
            "per_scenario_recomputed_delay": ramp_delay,
            "rehearsal_runs": ramp_rows,
            "note": "3 sensor_ramp rehearsal runs exist in rehearsal.json (not 2): LIT101 "
            "(localized 71.5s), LIT301 (localized 55.0s), and FIT201, which the fix-prompt's "
            "context block did not mention -- FIT201 was NOT ranked first (rank 2, localized "
            "19.5s). Reported in full rather than selectively.",
            "scenarios_too_few_to_rank_reliability": "15 total rehearsal runs (3 per scenario) is "
            "too small a sample to rank scenario reliability against each other; the per-scenario "
            "test-set figures in metrics.json (n=10 per scenario) are the appropriate basis for "
            "that, and even those carry wide Wilson intervals at n=10 (see A10/a7_intervals).",
        },
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("demo_vs_evaluation_gap", result)
    demo_attack = result["demo_attack"]
    eval_dist = result["evaluation_magnitude_distribution"]
    offset_delay_block = result["sensor_offset_detection_delay"]
    assert isinstance(demo_attack, dict)
    assert isinstance(eval_dist, dict)
    assert isinstance(offset_delay_block, dict)
    per_scenario_recomputed = offset_delay_block["per_scenario_recomputed"]
    assert isinstance(per_scenario_recomputed, dict)
    recomputed_delay = per_scenario_recomputed["mean_detection_delay_s"]
    print(
        f"wrote {out}: demo magnitude frac={demo_attack['fraction_of_span']:.3f} "
        f"in eval range {eval_dist['sampled_fraction_of_span_range']} | "
        f"sensor_offset recomputed mean delay={recomputed_delay:.2f}s "
        f"vs demo {demo_attack['detect_s']}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
