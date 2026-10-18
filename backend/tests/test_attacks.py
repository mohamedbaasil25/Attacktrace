"""Each scenario must produce its expected physical effect versus a clean twin (same seed)."""

import numpy as np
import pytest

from app.attacks import AttackEngine, AttackSpec, Scenario
from app.sim import Plant

DT = 0.1


def _run(spec: AttackSpec | None, seconds: float, seed: int = 4) -> tuple[Plant, AttackEngine]:
    eng = AttackEngine()
    if spec is not None:
        eng.schedule(spec)
    p = Plant(seed=seed, overlay=eng)
    for _ in range(round(seconds / DT)):
        p.step()
    return p, eng


def _pair(spec: AttackSpec, seconds: float) -> tuple[Plant, Plant]:
    return _run(spec, seconds)[0], _run(None, seconds)[0]


def test_sensor_freeze_holds_reported_value() -> None:
    eng = AttackEngine()
    eng.schedule(AttackSpec(Scenario.SENSOR_FREEZE, "LIT101", 5.0, 60.0))
    p = Plant(seed=4, overlay=eng)
    reported, truth = [], []
    for _ in range(round(60 / DT)):
        p.step()
        if p.t > 6.0:
            reported.append(p.state()["LIT101"])
            truth.append(p.physical_truth()["LIT101"])
    assert np.ptp(reported) == 0.0  # frozen exactly
    assert np.ptp(truth) > 1.0  # real level keeps moving (loop is now open)


def test_sensor_offset_drives_true_level_up() -> None:
    atk, clean = _pair(AttackSpec(Scenario.SENSOR_OFFSET, "LIT101", 5.0, 200.0, -20.0), 120)
    t_atk, t_clean = atk.physical_truth(), clean.physical_truth()
    assert t_atk["LIT101"] - t_clean["LIT101"] > 15.0  # PLC1 fooled → overfills T1
    assert atk.state()["LIT101"] - t_atk["LIT101"] == pytest.approx(-20.0, abs=1.0)


def test_large_offset_creates_overflow_risk() -> None:
    eng = AttackEngine()
    eng.schedule(AttackSpec(Scenario.SENSOR_OFFSET, "LIT101", 5.0, 300.0, -45.0))
    p = Plant(seed=4, overlay=eng)
    etas = []
    for _ in range(round(60 / DT)):
        p.step()
        etas.append(p.impact().t1_overflow_s)
    assert any(e is not None and e < 300 for e in etas)


def test_sensor_ramp_drifts_linearly() -> None:
    eng = AttackEngine()
    eng.schedule(AttackSpec(Scenario.SENSOR_RAMP, "LIT301", 0.0, 100.0, 20.0))
    p = Plant(seed=4, overlay=eng)
    bias: dict[int, float] = {}
    for _ in range(round(100 / DT)):
        p.step()
        sec = round(p.t, 1)
        if sec in (25.0, 50.0, 75.0):
            bias[int(sec)] = p.state()["LIT301"] - p.physical_truth()["LIT301"]
    assert bias[25] == pytest.approx(5.0, abs=1.0)
    assert bias[50] == pytest.approx(10.0, abs=1.0)
    assert bias[75] == pytest.approx(15.0, abs=1.0)


def test_actuator_force_pump_off_stops_flow() -> None:
    atk, clean = _pair(AttackSpec(Scenario.ACTUATOR_FORCE, "P101", 5.0, 200.0, 0.0), 60)
    a, c = atk.physical_truth(), clean.physical_truth()
    assert a["FIT201"] < 0.2
    assert a["LIT101"] > c["LIT101"] + 3.0
    assert a["LIT301"] < c["LIT301"] - 3.0


def test_actuator_force_valve_open_wastes_energy() -> None:
    atk, _ = _pair(AttackSpec(Scenario.ACTUATOR_FORCE, "MV101", 5.0, 200.0, 1.0), 120)
    assert atk.physical_truth()["MV101"] > 0.99
    assert atk.impact().energy_wasted_kwh > 0.01


def test_rogue_setpoint_moves_level() -> None:
    atk, clean = _pair(AttackSpec(Scenario.ROGUE_SETPOINT, "PLC2", 5.0, 300.0, 30.0), 150)
    assert atk.setpoints["PLC2"] == 80.0
    assert atk.physical_truth()["LIT301"] - clean.physical_truth()["LIT301"] > 20.0


def test_attack_ends_after_duration() -> None:
    eng = AttackEngine()
    eng.schedule(AttackSpec(Scenario.SENSOR_OFFSET, "FIT201", 0.0, 10.0, 3.0))
    p = Plant(seed=4, overlay=eng)
    for _ in range(round(20 / DT)):
        p.step()
    assert eng.active(p.t) == []
    assert abs(p.state()["FIT201"] - p.physical_truth()["FIT201"]) < 0.5


def test_ground_truth_recorded() -> None:
    eng = AttackEngine()
    aid = eng.schedule(AttackSpec(Scenario.ROGUE_SETPOINT, "PLC1", 12.0, 30.0, 10.0))
    (gt,) = eng.ground_truth()
    assert aid == gt.attack_id == "atk_001"
    assert (gt.target, gt.origin_type, gt.mitre) == ("PLC1", "controller", "T0855")
    assert (gt.start_s, gt.end_s) == (12.0, 42.0)


@pytest.mark.parametrize(
    ("scenario", "target", "magnitude"),
    [
        (Scenario.SENSOR_OFFSET, "P101", 1.0),
        (Scenario.ACTUATOR_FORCE, "LIT101", 1.0),
        (Scenario.ROGUE_SETPOINT, "MV101", 5.0),
        (Scenario.ACTUATOR_FORCE, "P101", 2.0),
    ],
)
def test_invalid_specs_rejected(scenario: Scenario, target: str, magnitude: float) -> None:
    with pytest.raises(ValueError):
        AttackEngine().schedule(AttackSpec(scenario, target, 0.0, 10.0, magnitude))


def test_attack_is_deterministic() -> None:
    spec = AttackSpec(Scenario.SENSOR_RAMP, "PIT301", 3.0, 40.0, 0.3)
    a, _ = _run(spec, 30, seed=8)
    b, _ = _run(spec, 30, seed=8)
    assert a.state() == b.state()


def test_freeze_does_not_leak_across_reset() -> None:
    eng = AttackEngine()
    eng.schedule(AttackSpec(Scenario.SENSOR_FREEZE, "LIT101", 5.0, 100.0))
    p = Plant(seed=1, overlay=eng)
    for _ in range(100):
        p.step()
    first = p.state()["LIT101"]
    p.reset(1)
    for _ in range(100):
        p.step()
    # Frozen at the pre-attack reading of the *new* run, which equals the first run (same seed).
    assert p.state()["LIT101"] == first
    p.reset(2)
    for _ in range(100):
        p.step()
    assert p.state()["LIT101"] != first
