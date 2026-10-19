"""Phase 14 A5: distribution of baseline 3-sigma alarm counts over the 50 held-out SIM attacks.

The README/Documentation/Slides/Demo_Script "6 alarms" figure is sourced to "live run via
/ws/live" -- i.e. ONE anecdotal demo run, not a measured distribution over the held-out set. This
recomputes the baseline's cumulative alarmed-node set (the same accumulation the engine does:
`BaselineDetector.alarms()` unioned sample by sample) for each of the 50 held-out attacks, over the
window from the attack's true start to the end of that run (a superset of the engine's own
incident-open-to-close window, since the exact close time isn't saved; documented as such -- this
makes the reported numbers, if anything, an upper bound, not an underclaim).
"""

import numpy as np

from app.attacks import Scenario
from app.config import get_settings
from app.data.simdata import attack_run
from app.detect.pipeline import load_baseline
from eval.analysis._util import merge_write
from eval.detection import TEST_ATTACK_SEEDS


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def analyze() -> dict[str, object]:
    settings = get_settings()
    base = load_baseline(settings.models_dir)
    counts: list[int] = []
    per_scenario: dict[str, list[int]] = {sc.value: [] for sc in Scenario}
    for sc in Scenario:
        for s in TEST_ATTACK_SEEDS:
            r = attack_run(s, sc)
            assert r.truth is not None
            start = int(np.searchsorted(r.t, r.truth.start_s))
            breaches = base.breaches(r.x[start:])
            alarmed = {base.names[i] for i in np.flatnonzero(breaches.any(axis=0))}
            counts.append(len(alarmed))
            per_scenario[sc.value].append(len(alarmed))
    return {
        "n_attacks": len(counts),
        "method": "cumulative distinct baseline-alarmed nodes from attack true-start to end of "
        "the (short, seeded) test run; an upper bound on the engine's own incident-window count, "
        "since the exact incident-close sample isn't saved for these runs.",
        "mean": float(np.mean(counts)),
        "median": _pct([float(c) for c in counts], 0.5),
        "max": max(counts),
        "min": min(counts),
        "anecdotal_demo_figure": 6,
        "anecdotal_figure_is_within_range": min(counts) <= 6 <= max(counts),
        "per_scenario_mean": {k: float(np.mean(v)) for k, v in per_scenario.items()},
    }


def main() -> int:
    result = analyze()
    out = merge_write("alarm_flood", result)
    print(
        f"wrote {out}: n={result['n_attacks']} mean={result['mean']:.1f} "
        f"median={result['median']:.1f} max={result['max']} min={result['min']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
