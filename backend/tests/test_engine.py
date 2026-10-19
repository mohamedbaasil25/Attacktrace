import time

import pytest

from app.attacks import Scenario
from app.engine import CLOSE_SAMPLES, WARMUP_SAMPLES, Engine, _has_hazard
from app.schemas import AttackRequest, LiveMessage
from app.sim import NODE_IDS


def run(engine: Engine, seconds: float) -> list[LiveMessage]:
    return [engine.step_sample() for _ in range(round(seconds / 0.5))]


def test_message_shape_and_cadence(engine: Engine) -> None:
    msg = engine.step_sample()
    assert [n.id for n in msg.nodes] == list(NODE_IDS)
    assert msg.mode == "sim" and msg.incident is None and msg.alert is None
    assert msg.impact is not None and msg.impact.energy_wasted_kwh == 0.0
    # No incident, so nothing may be marked origin/affected (a warmed detector may flag "suspect").
    assert all(n.truth is not None and n.status in {"normal", "suspect"} for n in msg.nodes)
    warm = WARMUP_SAMPLES * 0.5  # the detector is warmed up silently before the first message
    assert engine._plant.t == pytest.approx(warm + 0.5)  # one emit period per sample


def test_clean_run_raises_no_incident(engine: Engine) -> None:
    msgs = run(engine, 200)
    assert all(m.incident is None for m in msgs) and engine.incidents == []


def test_attack_produces_localized_incident(engine: Engine) -> None:
    run(engine, 60)
    attack_id = engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))
    assert attack_id == "atk_001"
    first = None
    statuses = []
    for _ in range(240):
        t0 = time.perf_counter()
        m = engine.step_sample()
        dt = time.perf_counter() - t0
        if m.incident is not None:
            statuses.append(m.incident.status)
            if first is None:
                first = m
                assert m.alert is not None  # alert and incident are emitted together
                assert dt < 1.0  # decision latency
    assert first is not None
    inc = engine.incidents[0]
    assert inc.id == "inc_001"
    assert "P101" in [o.id for o in inc.origin]
    assert inc.ground_truth is not None and inc.ground_truth.target == "P101"
    assert inc.ground_truth.attack_id == attack_id
    assert sum(o.confidence for o in inc.origin) <= 1.0
    assert statuses[0] == "localizing" and "open" in statuses
    assert len(inc.explanation) < 140 and inc.baseline_alarms
    assert engine.latest is not None
    assert any(n.status == "origin" for n in engine.latest.nodes)


def test_invalid_attack_rejected(engine: Engine) -> None:
    with pytest.raises(ValueError):
        engine.launch(AttackRequest(scenario=Scenario.SENSOR_OFFSET, target="P101"))


def test_reset_clears_everything(engine: Engine) -> None:
    run(engine, 30)
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))
    run(engine, 60)
    engine.reset()
    assert engine.incidents == [] and engine.latest is None
    again = AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P301")
    assert engine.launch(again) == "atk_001"
    assert engine.step_sample().incident is None
    assert engine._plant.t == pytest.approx(WARMUP_SAMPLES * 0.5 + 0.5)


def test_incident_closes_after_attack_ends(engine: Engine) -> None:
    run(engine, 40)
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=40))
    run(engine, 400)
    assert engine.incidents and engine.incidents[0].status == "closed"


def test_detector_is_warm_before_the_first_message(engine: Engine) -> None:
    """Regression: the detector's first `window` scores are zeros. An attack launched right after
    a start or reset used to be ranked worse because its onset fell inside that gap."""
    det = engine.loaded.detector
    assert len(det._buf) == det.window  # window already full
    assert engine._k == WARMUP_SAMPLES and engine.latest is None and engine.incidents == []
    first = engine.step_sample()
    assert max(n.score for n in first.nodes) > 0.0  # real scores from the very first message
    engine.reset()
    assert len(det._buf) == det.window and engine._k == WARMUP_SAMPLES


def test_incident_stays_open_while_a_physical_hazard_persists(engine: Engine) -> None:
    """Regression: a persistent offset stops raising alerts once the plant settles, and the
    incident used to close 30 s later while a tank was still overfilling (overflow ETA shown)."""
    run(engine, 10)
    for target, value in (("MV101", 1.0), ("P101", 0.0)):  # fill T1 and stop draining it
        req = AttackRequest(
            scenario=Scenario.ACTUATOR_FORCE, target=target, magnitude=value, duration_s=900
        )
        engine.launch(req)
    for _ in range(600):  # wait for the overflow estimate: the precondition of this test
        m = engine.step_sample()
        if _has_hazard(m.impact):  # type: ignore[arg-type]
            break
    else:
        pytest.fail("the attack never produced a hazard, so this test would prove nothing")
    assert m.incident is not None

    held = 0
    for _ in range(100):  # 50 s, longer than the 30 s close time
        engine._run = 0  # the alert is quiet from here on, as it is for a settled spoof
        m = engine.step_sample()
        if m.impact is None or not _has_hazard(m.impact):
            break
        assert m.incident is not None and m.incident.status != "closed"
        held += 1
    assert held >= CLOSE_SAMPLES + 2, f"hazard ended after only {held} samples"


def test_origin_candidates_carry_a_breakdown(engine: Engine) -> None:
    """Phase 11 B1: incident candidates include the weights and the per-signal contributions."""
    run(engine, 60)
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))
    run(engine, 40)
    inc = engine.incidents[0]
    for o in inc.origin:
        assert o.breakdown is not None and o.weights is not None
        assert o.weights.deviation + o.weights.onset + o.weights.causal == pytest.approx(1.0)
        assert min(o.breakdown.deviation, o.breakdown.onset, o.breakdown.causal) >= 0.0
        assert o.breakdown.deviation <= o.weights.deviation + 1e-9


def test_incident_reports_the_ambiguity_flag(engine: Engine) -> None:
    run(engine, 60)
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))
    run(engine, 40)
    inc = engine.incidents[0]
    gap = inc.origin[0].confidence - inc.origin[1].confidence
    assert inc.ambiguous == (gap < engine.settings.gate_margin)
