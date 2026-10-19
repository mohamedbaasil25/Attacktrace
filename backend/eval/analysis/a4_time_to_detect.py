"""Phase 14 A4: time-to-detect (attack start -> first alert), median/p90/n, per mode.

`reports/metrics.json` and `reports/live_metrics.json` only saved the MEAN detection delay, not
the per-attack list a median/p90 needs. This recomputes the per-attack delay list via a read-only
forward pass of the already-trained, already-frozen detector (`_compute.py`) -- deterministic, no
model/weight/threshold change, not a "tuning on evaluation data" rerun under Phase 14 rule 2. The
recomputed mean is checked against the committed mean as a consistency guard.
"""

import json

from eval.analysis._compute import hai_forward, sim_forward
from eval.analysis._util import merge_write, reports_dir


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def analyze() -> dict[str, object]:
    sim_committed = json.loads((reports_dir() / "metrics.json").read_text())
    live = json.loads((reports_dir() / "live_metrics.json").read_text())

    sim = sim_forward()
    sim_recomputed_mean = (
        sum(sim.attack_delays) / len(sim.attack_delays) if sim.attack_delays else None
    )
    sim_committed_mean = sim_committed["detection"]["attacktrace"]["mean_detection_delay_s"]

    live_delays = [
        a["detection_delay_s"] for a in live["attacks"] if a["detection_delay_s"] is not None
    ]
    live_missed = sum(1 for a in live["attacks"] if a["detection_delay_s"] is None)

    hai = hai_forward()

    return {
        "sim": {
            "n": sim.n_attacks,
            "n_detected": sim.n_attacks - sim.n_attacks_missed,
            "n_missed": sim.n_attacks_missed,
            "median_s": _pct(sim.attack_delays, 0.5),
            "p90_s": _pct(sim.attack_delays, 0.9),
            "recomputed_mean_s": sim_recomputed_mean,
            "committed_mean_s": sim_committed_mean,
            "consistency_check": "match"
            if sim_recomputed_mean is not None
            and abs(sim_recomputed_mean - sim_committed_mean) < 1e-6
            else "MISMATCH -- recompute does not reproduce the committed mean, investigate",
        },
        "live": {
            "n": len(live["attacks"]),
            "n_detected": len(live_delays),
            "n_missed": live_missed,
            "median_s": _pct(live_delays, 0.5),
            "p90_s": _pct(live_delays, 0.9),
            "committed_mean_s": live["localization"]["mean_detection_delay_s"],
        },
        "hai": (
            {
                "n_windows": hai.n_windows,
                "n_detected": hai.n_windows - hai.n_windows_missed,
                "n_missed": hai.n_windows_missed,
                "median_s": _pct(hai.window_delays, 0.5),
                "p90_s": _pct(hai.window_delays, 0.9),
            }
            if hai is not None
            else "skipped: no trained HAI model under backend/models/hai/"
        ),
    }


def main() -> int:
    result = analyze()
    out = merge_write("time_to_detect", result)
    sim, live = result["sim"], result["live"]
    assert isinstance(sim, dict) and isinstance(live, dict)
    print(
        f"wrote {out}: SIM median={sim['median_s']:.1f}s p90={sim['p90_s']:.1f}s "
        f"n={sim['n']} missed={sim['n_missed']} ({sim['consistency_check']}) | "
        f"LIVE median={live['median_s']:.1f}s p90={live['p90_s']:.1f}s n={live['n']} "
        f"missed={live['n_missed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
