import numpy as np
import pytest

from app.attacks import AttackEngine, AttackSpec, Scenario
from app.sim import NODE_IDS, PID_EDGES, Plant
from app.sim.cli import main as cli_main
from app.sim.pid import PID


def _trace(plant: Plant, steps: int) -> np.ndarray:
    rows = []
    for _ in range(steps):
        plant.step()
        s = plant.state()
        rows.append([s[n] for n in NODE_IDS])
    return np.array(rows)


def test_determinism_same_seed() -> None:
    a, b = _trace(Plant(seed=7), 600), _trace(Plant(seed=7), 600)
    assert np.array_equal(a, b)


def test_different_seed_differs() -> None:
    assert not np.array_equal(_trace(Plant(seed=1), 200), _trace(Plant(seed=2), 200))


def test_reset_reproduces() -> None:
    p = Plant(seed=11)
    first = _trace(p, 300)
    p.reset(11)
    assert p.t == pytest.approx(0.0)
    assert np.array_equal(first, _trace(p, 300))


def test_clean_run_stays_in_band() -> None:
    p = Plant(seed=3)
    truth = []
    for _ in range(3000):  # 5 min
        p.step()
        truth.append([p.physical_truth()[n] for n in ("LIT101", "LIT301")])
    levels = np.array(truth)
    assert levels.min() > 40.0 and levels.max() < 60.0
    im = p.impact()
    assert im.overflow_l == 0.0
    assert im.energy_wasted_kwh == 0.0
    assert im.t1_overflow_s is None and im.t2_dry_s is None


def test_clean_state_reported_tracks_truth() -> None:
    p = Plant(seed=5)
    _trace(p, 100)
    s, t = p.state(), p.physical_truth()
    assert set(s) == set(NODE_IDS) == set(t)
    assert abs(s["LIT101"] - t["LIT101"]) < 1.0


def test_signals_vary_under_normal_operation() -> None:
    # Detectors and Granger need non-constant signals.
    data = _trace(Plant(seed=9), 1200)
    assert (data.std(axis=0) > 1e-3).all()


def test_mass_balance_overflow_and_dry() -> None:
    eng = AttackEngine()
    for target, value in (("MV101", 1.0), ("P101", 0.0), ("P301", 1.0)):
        eng.schedule(AttackSpec(Scenario.ACTUATOR_FORCE, target, 0.0, 999.0, value))
    p = Plant(seed=1, overlay=eng)
    p.l1, p.l2 = 95.0, 5.0
    for _ in range(300):
        p.step()
    assert p.l1 == 100.0 and p.overflow_l > 0.0  # T1 capped, spill counted
    assert p.l2 < 3.0  # T2 drawn down to suction loss
    assert p.physical_truth()["FIT201"] < 1e-6
    assert p.impact().pump_stress["P301"] > 0.0


def test_pid_clamps_and_antiwindup() -> None:
    c = PID(kp=1.0, ki=1.0)
    for _ in range(100):
        out = c.update(10.0, 0.1)
    assert out == 1.0
    assert c.integral < 1.0  # stopped integrating once saturated


def test_pid_edges_reference_known_nodes() -> None:
    for a, b in PID_EDGES:
        assert a in NODE_IDS and b in NODE_IDS


def test_cli_prints_30s(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["--seconds", "30"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 31  # header + 30 rows
    assert lines[-1].split()[0] == "30.0"
