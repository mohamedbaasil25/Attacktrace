"""Phase 14 A2: LIVE latency/throughput, and the SIM-vs-LIVE time-to-localize definition gap.

Everything here is read from already-saved files (`metrics.json`, `live_metrics.json`) plus the
source code of the two eval harnesses (`eval/localization.py`, `eval/live.py`) that produced those
numbers -- no new run. Stale/missing tag counts were not separately logged by `eval.live` (which
never exercises the fault path -- see a1_live_miss.py); they are reported as "not measured" rather
than invented, per Part A's own instruction to say so explicitly rather than guess.
"""

import json

from eval.analysis._util import merge_write, reports_dir


def analyze() -> dict[str, object]:
    sim = json.loads((reports_dir() / "metrics.json").read_text())
    live = json.loads((reports_dir() / "live_metrics.json").read_text())

    sim_ttl = sim["localization"]["mean_time_to_localize_s"]
    sim_delay = sim["detection"]["attacktrace"]["mean_detection_delay_s"]
    live_ttl = live["localization"]["mean_time_to_localize_s"]
    live_delay = live["localization"]["mean_detection_delay_s"]
    forward_s = sim["localization"]["window"]["forward_s"]

    return {
        "definitions": {
            "sim_time_to_localize_s": (
                "eval/localization.py:66 -- (sample time of the first alert at/after attack "
                f"start) + window.forward_s ({forward_s} s, a fixed localization-refinement "
                "window) - attack true start time. Source: reports/metrics.json "
                "localization.window.forward_s."
            ),
            "live_time_to_localize_s": (
                "eval/live.py: Incident.detected_at (set once, at the ORIGINAL alert) - attack "
                "launch send time. No fixed window is added. Source: eval/live.py "
                "LiveEvalState.run_attack / AttackResult.time_to_localize_s."
            ),
            "verdict": (
                "The two 'time to localize' numbers are NOT on a common basis: SIM's is "
                f"inflated by a fixed +{forward_s:.1f} s window that LIVE's does not add. "
                "They should not be presented as directly comparable without this note."
            ),
        },
        "common_basis_detection_delay_s": {
            "meaning": "attack start/launch -> first alert, same definition in both harnesses "
            "(eval/detection.py:54 for SIM, eval/live.py LiveEvalState.tick for LIVE) -- this IS "
            "a fair comparison.",
            "sim": sim_delay,
            "live": live_delay,
            "gap_s": sim_delay - live_delay,
        },
        "mismatched_basis_time_to_localize_s": {
            "sim": sim_ttl,
            "live": live_ttl,
            "sim_minus_forward_window_s": sim_ttl - forward_s,
            "note": f"sim_minus_forward_window_s is SIM's number with the same "
            f"+{forward_s:.1f}s window LIVE never adds subtracted back out, to make a rough "
            "common-basis estimate; it is "
            "not a recomputation from raw timestamps (those per-sample timestamps were not "
            "saved), so treat it as an approximation, not a third measured figure.",
        },
        "live_latency_ms": live["latency_ms"],
        "live_samples_per_s": live["samples_per_s"],
        "live_dropped": live["dropped"],
        "live_stale_missing_counts": "not measured: eval.live does not log per-poll quality "
        "state, only the final aggregate (samples_per_s, dropped). A fresh instrumented run would "
        "be needed for a direct count; not run here to avoid re-touching the LIVE evidence files "
        "without a specific need (dropped=0 and p99=3.0 ms well under stale_after_s=1.0 s both "
        "point at near-zero staleness during this run, but that is an inference, not a count).",
    }


def main() -> int:
    result = analyze()
    out = merge_write("latency_and_timing", result)
    d = result["common_basis_detection_delay_s"]
    assert isinstance(d, dict)
    print(f"wrote {out}: common-basis detection delay SIM {d['sim']:.2f}s vs LIVE {d['live']:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
