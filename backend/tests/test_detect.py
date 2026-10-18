import numpy as np
import pytest
import torch

from app.attacks import AttackSpec, Scenario
from app.data.simdata import SAMPLE_HZ, attack_run, sample_attack, simulate
from app.detect.baseline import BaselineDetector
from app.detect.detector import (
    ForecastDetector,
    aggregate,
    alert_mask,
    best_threshold,
    fit_err_sd,
    sustained,
)
from app.detect.forecaster import GDN, WINDOW, Norm, build_model, make_windows, train
from app.graph import adjacency, static_graph
from app.sim import NODE_IDS

N = len(NODE_IDS)


def test_simulate_shape_and_labels() -> None:
    spec = AttackSpec(Scenario.SENSOR_OFFSET, "LIT101", 50.0, 60.0, -20.0)
    r = simulate(1, 200.0, spec)
    assert r.x.shape == (round(200 * SAMPLE_HZ), N)
    y = r.labels()
    assert y[r.t < 50].max() == 0 and (y[(r.t >= 50) & (r.t < 110)] == 1).all()
    assert (y[(r.t >= 110) & (r.t < 170)] == -1).all()


def test_sample_attack_valid_for_every_scenario() -> None:
    rng = np.random.default_rng(0)
    for sc in Scenario:
        run = attack_run(5, sc)
        assert run.truth is not None and run.truth.scenario is sc
        assert sample_attack(rng, sc).scenario is sc


def test_make_windows_alignment() -> None:
    x = np.arange(30, dtype=float).reshape(15, 2)
    w, y = make_windows(x, 4)
    assert w.shape == (11, 4, 2) and y.shape == (11, 2)
    assert (w[0] == x[:4]).all() and (y[0] == x[4]).all()


def test_sustained_and_aggregate() -> None:
    m = np.array([1, 1, 0, 1, 1, 1, 1, 0], dtype=bool)
    assert sustained(m, 3).tolist() == [False, False, False, False, False, True, True, False]
    assert aggregate(np.array([[1.0, 5.0, 3.0]]), k=2)[0] == pytest.approx(4.0)


def test_best_threshold_separates_classes() -> None:
    rng = np.random.default_rng(0)
    agg = np.concatenate([rng.normal(1, 0.1, 300), rng.normal(3, 0.1, 300)])
    y = np.concatenate([np.zeros(300), np.ones(300)]).astype(np.int8)
    thr, f1 = best_threshold([(agg, y)])
    assert 1.2 < thr < 3.0 and f1 > 0.95


def test_gdn_respects_graph_mask() -> None:
    adj = adjacency(static_graph())
    model = GDN(N, WINDOW, adj)
    x = torch.randn(4, WINDOW, N)
    out = model(x)
    i, j = NODE_IDS.index("MV101"), NODE_IDS.index("P301")  # P301 is not a parent of MV101
    assert not adj[i, j]
    x2 = x.clone()
    x2[:, :, j] += 10.0
    assert torch.allclose(model(x2)[:, i], out[:, i], atol=1e-5)


@pytest.fixture(scope="module")
def tiny_detector() -> ForecastDetector:
    train_runs = [simulate(s, 300.0).x for s in (11, 12, 13)]
    val_run = simulate(14, 300.0).x
    norm = Norm.fit(np.vstack(train_runs))
    tx = [make_windows(norm.apply(x)) for x in train_runs]
    xy = (np.concatenate([a for a, _ in tx]), np.concatenate([b for _, b in tx]))
    model = build_model("gdn", N, WINDOW, adjacency(static_graph()))
    train(model, xy, make_windows(norm.apply(val_run)), epochs=15)
    return ForecastDetector(model, norm, fit_err_sd(model, norm, [val_run]))


def test_streaming_matches_batch(tiny_detector: ForecastDetector) -> None:
    x = simulate(21, 60.0).x
    batch = tiny_detector.score_run(x)
    tiny_detector.reset()
    stream = np.array([tiny_detector.update(row) for row in x])
    assert np.allclose(batch, stream, atol=1e-4)


def test_actuator_attack_scores_above_clean(tiny_detector: ForecastDetector) -> None:
    spec = AttackSpec(Scenario.ACTUATOR_FORCE, "P101", 90.0, 120.0, 0.0)
    atk, clean = simulate(22, 300.0, spec), simulate(22, 300.0)
    a = aggregate(tiny_detector.score_run(atk.x))
    c = aggregate(tiny_detector.score_run(clean.x))
    assert a[(atk.t >= 95) & (atk.t < 210)].max() > 2 * c.max()
    assert alert_mask(a, float(c.max()) * 1.2).any()


def test_baseline_flags_large_offset() -> None:
    train_x = np.vstack([simulate(s, 300.0).x for s in (31, 32)])
    base = BaselineDetector().fit(train_x)
    spec = AttackSpec(Scenario.SENSOR_OFFSET, "LIT101", 30.0, 100.0, -25.0)
    r = simulate(33, 150.0, spec)
    # The step is obvious; once PLC1 compensates, the 3-sigma band stops seeing it.
    onset = np.searchsorted(r.t, 30.0)
    assert base.alert(r.x)[onset + 1 : onset + 4].all()
    assert "LIT101" in base.alarms(r.x[onset + 1])
    assert not base.alert(simulate(34, 150.0).x).mean() > 0.05


def test_rising_edges() -> None:
    from app.detect.detector import rising_edges

    m = np.array([1, 1, 0, 0, 1, 0, 1, 1], dtype=bool)
    assert rising_edges(m).tolist() == [0, 4, 6]


def test_stuck_sensor_flagged_immediately(tiny_detector: ForecastDetector) -> None:
    spec = AttackSpec(Scenario.SENSOR_FREEZE, "LIT101", 60.0, 100.0)
    atk, clean = simulate(23, 200.0, spec), simulate(23, 200.0)
    k = NODE_IDS.index("LIT101")
    a, c = tiny_detector.score_run(atk.x), tiny_detector.score_run(clean.x)
    on = (atk.t >= 66) & (atk.t < 150)
    assert a[on, k].min() > 3.0 > c[:, k].max()
    tiny_detector.reset()
    stream = np.array([tiny_detector.update(row) for row in atk.x])
    assert np.allclose(a, stream, atol=1e-4)
