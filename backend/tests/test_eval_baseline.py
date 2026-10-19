from pathlib import Path

import numpy as np

from app.attacks import AttackSpec, Scenario
from app.data.simdata import simulate
from app.detect.baseline import BaselineDetector
from app.sim import NODE_IDS
from eval.localization import baseline_rank, evaluate_baseline_localization


def fitted() -> BaselineDetector:
    return BaselineDetector().fit(np.vstack([simulate(s, 300.0).x for s in (31, 32)]))


def test_rank_puts_the_first_breaching_node_first() -> None:
    base = fitted()
    spec = AttackSpec(Scenario.SENSOR_OFFSET, "FIT201", 60.0, 100.0, 4.0)
    run = simulate(33, 200.0, spec)
    onset = int(np.searchsorted(run.t, 60.0))
    ranked = baseline_rank(base, run.x, onset + 2)
    assert ranked[0] == "FIT201"
    assert sorted(ranked) == sorted(NODE_IDS)  # a full ordering of every node


def test_rank_breaks_ties_by_larger_deviation() -> None:
    base = fitted()
    x = np.tile(base.norm.mu if base.norm else np.zeros(len(NODE_IDS)), (30, 1))
    assert base.norm is not None
    i, j = NODE_IDS.index("LIT101"), NODE_IDS.index("LIT301")
    x[10:, i] += 4 * base.norm.sd[i]  # both breach on the same sample...
    x[10:, j] += 9 * base.norm.sd[j]  # ...but LIT301 breaches harder
    ranked = baseline_rank(base, x, 12)
    assert ranked[:2] == ["LIT301", "LIT101"]


def test_missed_attacks_count_as_misses() -> None:
    base = fitted()
    spec = AttackSpec(Scenario.SENSOR_OFFSET, "FIT201", 60.0, 100.0, 4.0)
    hit = simulate(34, 200.0, spec)
    quiet = simulate(35, 200.0, AttackSpec(Scenario.SENSOR_OFFSET, "FIT201", 60.0, 100.0, 0.0))
    out = evaluate_baseline_localization(base, [hit, quiet])
    assert out["n_runs"] == 2
    assert out["top1"] == 0.5  # the zero-magnitude "attack" never alerts
    assert out["top3"] == 0.5


def test_baseline_saved_before_names_existed_still_works(tmp_path: Path) -> None:
    """Regression: a SIM baseline pickled without `names` crashed the live loop on the first
    incident (AttributeError in alarms())."""
    import joblib

    base = fitted()
    del base.__dict__["names"]  # what an older pickle looks like when loaded
    joblib.dump(base, tmp_path / "old.joblib")
    old = joblib.load(tmp_path / "old.joblib")
    assert "names" not in old.__dict__
    x = np.tile(old.norm.mu, (3, 1))
    x[:, NODE_IDS.index("LIT101")] += 10 * old.norm.sd[NODE_IDS.index("LIT101")]
    assert old.alarms(x[0]) == ["LIT101"]
    assert old.names == NODE_IDS
