"""Phase 14 A7: Wilson 95% intervals for every headline rate.

Per-attack proportions (Top-1, Top-3, containment, ambiguity) use the exact k/n already saved in
`metrics.json`/`live_metrics.json`. Precision/recall are per-SAMPLE proportions over thousands of
2 Hz ticks; their raw tp/fp/fn counts were not saved, only the ratios, so they are recomputed via
the same read-only forward pass as a4 (`_compute.py`) for SIM and HAI. LIVE precision/recall would
need the same recompute over its ~2h53m real-time run, which was not re-run here -- flagged as
not computed rather than estimated.
"""

import json

from eval.analysis._compute import hai_forward, sim_forward
from eval.analysis._util import merge_write, reports_dir, wilson


def analyze() -> dict[str, object]:
    sim = json.loads((reports_dir() / "metrics.json").read_text())
    live = json.loads((reports_dir() / "live_metrics.json").read_text())

    sim_fwd = sim_forward()
    hai_fwd = hai_forward()

    out: dict[str, object] = {
        "sim": {
            "top1": wilson(round(sim["localization"]["top1"] * 50), 50),
            "top3": wilson(round(sim["localization"]["top3"] * 50), 50),
            "precision": wilson(sim_fwd.tp, sim_fwd.tp + sim_fwd.fp),
            "recall": wilson(sim_fwd.tp, sim_fwd.tp + sim_fwd.fn),
            "isolate_top1": wilson(
                sim["isolation"]["isolate_top1"]["contained"], sim["isolation"]["isolate_top1"]["n"]
            ),
            "isolate_true_origin": wilson(
                sim["isolation"]["isolate_true_origin"]["contained"],
                sim["isolation"]["isolate_true_origin"]["n"],
            ),
            "isolate_wrong_node": wilson(
                sim["isolation"]["isolate_wrong_node"]["contained"],
                sim["isolation"]["isolate_wrong_node"]["n"],
            ),
            "ambiguous_rate": wilson(
                sim["ambiguity"]["n_ambiguous"], sim["ambiguity"]["n_incidents"]
            ),
        },
        "live": {
            "top1": wilson(
                round(live["localization"]["top1"] * live["n_attacks"]), live["n_attacks"]
            ),
            "top3": wilson(
                round(live["localization"]["top3"] * live["n_attacks"]), live["n_attacks"]
            ),
            "detected": wilson(live["n_detected"], live["n_attacks"]),
            "precision_recall": "not computed: would need a read-only recompute over the full "
            "~2h53m real-time eval.live run (raw per-tick labels were not saved); not re-run "
            "here without a specific need.",
        },
        "hai": (
            {
                "precision": wilson(hai_fwd.tp, hai_fwd.tp + hai_fwd.fp),
                "recall": wilson(hai_fwd.tp, hai_fwd.tp + hai_fwd.fn),
                "process_top1": wilson(round(sim["hai"]["localization"]["process_top1"] * 28), 28)
                if "hai" in sim
                else "metrics.json has no hai key",
            }
            if hai_fwd is not None
            else "skipped: no trained HAI model"
        ),
    }
    return out


def main() -> int:
    result = analyze()
    out = merge_write("intervals", result)
    s = result["sim"]
    assert isinstance(s, dict)
    top1 = s["top1"]
    print(
        f"wrote {out}: SIM top1={top1['p']:.2f} [{top1['lo']:.2f},{top1['hi']:.2f}] n={top1['n']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
