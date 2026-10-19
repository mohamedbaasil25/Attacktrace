"""Phase 13 Part D: the attacker tool. Emulator-only, allowlisted, audited."""

import asyncio
import copy
import socket
from pathlib import Path

import pytest
from attacker.allowlist import AllowlistError, check_host, is_loopback
from attacker.client import AttackerClient, AttackerError
from fastapi.testclient import TestClient
from plant_emulator.server import PlantEmulator

from app.attacks.engine import Scenario
from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.live.config import load_live
from app.live.runtime import LiveRuntime
from app.live.source import LiveSource
from app.live.tagmap import decode
from app.main import create_app
from tests.test_live_engine import FakeClock, feed

TAGMAP = Path(__file__).resolve().parents[2] / "config" / "tagmap.yaml"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ------------------------------------------------------------------------------- allowlist
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "127.5.5.5", "plant-emulator"])
def test_allowed_hosts_pass(host: str) -> None:
    check_host(host)  # does not raise


@pytest.mark.parametrize("host", ["", "   ", "attacker.example.com", "10.0.0.5", "8.8.8.8"])
def test_other_hosts_are_refused(host: str) -> None:
    with pytest.raises(AllowlistError):
        check_host(host)


def test_extra_hosts_come_only_from_the_explicit_allowlist() -> None:
    with pytest.raises(AllowlistError):
        check_host("scada-01.internal", "")
    check_host("scada-01.internal", "scada-01.internal,other-host")  # does not raise
    with pytest.raises(AllowlistError):
        check_host("not-listed.internal", "scada-01.internal")


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("127.9.9.9") and is_loopback("localhost")
    assert not is_loopback("plant-emulator") and not is_loopback("10.0.0.1")


def test_attacker_client_refuses_to_construct_against_a_bad_host() -> None:
    with pytest.raises(AllowlistError):
        AttackerClient("attacker.example.com", 502, None)  # type: ignore[arg-type]
    AttackerClient("127.0.0.1", 502, None, "")  # type: ignore[arg-type]  # does not raise


# ----------------------------------------------------------------- client, real emulator
@pytest.fixture
async def emu():  # type: ignore[no-untyped-def]
    from app.live.tagmap import load_tagmap

    tm = load_tagmap(TAGMAP)
    port = free_port()
    e = PlantEmulator(tm, seed=3, port=port, health_port=None)
    await e.start()
    yield e, tm, port
    await e.stop()


async def attacker_for(tm, port, **kw: object) -> AttackerClient:  # type: ignore[no-untyped-def]
    atk = AttackerClient("127.0.0.1", port, tm, **kw)  # type: ignore[arg-type]
    assert await atk.connect()
    return atk


async def read(emu: PlantEmulator, tag: str) -> float:
    t = emu.tagmap.get(tag)
    regs = await emu.server.async_getValues(emu.tagmap.device_id, 3, t.address, t.width)
    return decode(t, [int(r) for r in regs])


async def test_sensor_offset_writes_and_clears(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    attack_id = await atk.launch(Scenario.SENSOR_OFFSET, "LIT101", -25.0, 0.3)
    await e.tick()
    assert await read(e, "LIT101.spoof_offset") == pytest.approx(-25.0)
    assert e.plant.state()["LIT101"] < e.plant.physical_truth()["LIT101"] - 15.0
    rec = atk.launched[0]
    assert rec.attack_id == attack_id and rec.scenario is Scenario.SENSOR_OFFSET
    for _ in range(20):
        await e.tick()
        await asyncio.sleep(0.05)
    assert await read(e, "LIT101.spoof_offset") == pytest.approx(0.0)  # cleared after duration
    await atk.close()


async def test_sensor_freeze_writes_and_clears(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    await atk.launch(Scenario.SENSOR_FREEZE, "FIT201", 0.0, 0.3)
    await e.tick()
    assert await read(e, "FIT201.spoof_freeze") == 1
    for _ in range(20):
        await e.tick()
        await asyncio.sleep(0.05)
    assert await read(e, "FIT201.spoof_freeze") == 0
    await atk.close()


async def test_actuator_force_writes_and_clears_to_no_override(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    await atk.launch(Scenario.ACTUATOR_FORCE, "P101", 0.0, 0.3)
    await e.tick()
    assert await read(e, "P101.force") == pytest.approx(0.0)
    for _ in range(20):
        await e.tick()
        await asyncio.sleep(0.05)
    assert await read(e, "P101.force") == pytest.approx(-1.0)
    await atk.close()


async def test_rogue_setpoint_writes_and_clears(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    await atk.launch(Scenario.ROGUE_SETPOINT, "PLC1", 25.0, 0.3)
    await e.tick()
    assert await read(e, "PLC1.setpoint_delta") == pytest.approx(25.0)
    for _ in range(20):
        await e.tick()
        await asyncio.sleep(0.05)
    assert await read(e, "PLC1.setpoint_delta") == pytest.approx(0.0)
    await atk.close()


async def test_sensor_ramp_steps_up_then_clears(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    await atk.launch(Scenario.SENSOR_RAMP, "LIT301", 30.0, 3.0)
    await e.tick()
    assert await read(e, "LIT301.spoof_offset") == pytest.approx(0.0)
    for _ in range(13):  # ~1.3 s real time: after the first 1 s ramp step, before it clears
        await e.tick()
        await asyncio.sleep(0.1)
    mid = await read(e, "LIT301.spoof_offset")
    assert 0.0 < mid < 30.0 - 1e-6  # moved partway, never past the target
    for _ in range(35):  # past the 3 s duration
        await e.tick()
        await asyncio.sleep(0.1)
    assert await read(e, "LIT301.spoof_offset") == pytest.approx(0.0)  # cleared
    await atk.close()


async def test_invalid_target_and_bad_duration_are_refused(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    with pytest.raises(AttackerError, match="cannot target"):
        await atk.launch(Scenario.SENSOR_OFFSET, "P101", -5.0, 10.0)  # P101 is an actuator
    with pytest.raises(AttackerError, match="\\[0, 1\\]"):
        await atk.launch(Scenario.ACTUATOR_FORCE, "P101", 5.0, 10.0)
    with pytest.raises(AttackerError, match="duration_s"):
        await atk.launch(Scenario.SENSOR_OFFSET, "LIT101", -5.0, 0.0)
    assert atk.launched == []
    del e
    await atk.close()


async def test_a_refused_write_never_reaches_the_emulator() -> None:
    """Construction fails closed before any socket to a non-allowlisted host is even opened."""
    with pytest.raises(AllowlistError):
        AttackerClient("10.0.0.9", 502, None)  # type: ignore[arg-type]


async def test_ground_truth_is_recorded_in_the_emulator(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    attack_id = await atk.launch(Scenario.ACTUATOR_FORCE, "P101", 0.0, 0.2)
    for _ in range(3):
        await e.tick()
    assert e.truth and e.truth[0].node_id == "P101" and e.truth[0].scenario == "actuator_force"
    assert atk.launched[0].attack_id == attack_id
    await atk.close()


async def test_close_cancels_pending_clears(emu) -> None:  # type: ignore[no-untyped-def]
    e, tm, port = emu
    atk = await attacker_for(tm, port)
    await atk.launch(Scenario.SENSOR_OFFSET, "LIT101", -10.0, 30.0)
    await e.tick()
    assert await read(e, "LIT101.spoof_offset") == pytest.approx(-10.0)
    await atk.close()  # the 30 s clear never runs
    assert await read(e, "LIT101.spoof_offset") == pytest.approx(-10.0)


def test_cli_rejects_a_non_allowlisted_host() -> None:
    from attacker.cli import parse_args, run

    args = parse_args(
        ["sensor_offset", "LIT101", "--host", "attacker.example.com", "--port", "502"]
    )
    with pytest.raises(AllowlistError):
        asyncio.run(run(args))


def test_audit_log_has_one_line_per_write(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from app.live.tagmap import load_tagmap

    caplog.set_level(logging.INFO, logger="attacktrace.attacker")
    atk = AttackerClient("127.0.0.1", free_port(), load_tagmap(TAGMAP))
    with pytest.raises(AttackerError):
        asyncio.run(atk._write("LIT101.spoof_offset", 1.0))  # not connected: no write, no log
    assert not any("write tag=" in r.message for r in caplog.records)


# ------------------------------------------------------------------------------- end to end via API
def make_live(
    tiny: tuple[Loaded, BaselineDetector],
    clock: FakeClock,
    cfg,
    tm,  # type: ignore[no-untyped-def]
) -> LiveRuntime:
    loaded, base = copy.deepcopy(tiny)
    s = Settings(live_tagmap=TAGMAP, live_poll_s=0.05)
    rt = LiveRuntime(s, cfg, tm, source=LiveSource(cfg, tm, clock=clock), clock=clock)
    from app.graph import static_graph
    from app.live.engine import LiveEngine

    rt.engine = LiveEngine(loaded, base, static_graph(), s, rt.source, "gdn", clock=clock)
    rt.detector_kind = "gdn"
    return rt


async def test_attack_endpoint_writes_to_the_emulator_and_reveals_ground_truth(
    tiny: tuple[Loaded, BaselineDetector], engine
) -> None:  # type: ignore[no-untyped-def]
    port = free_port()
    s = Settings(live_tagmap=TAGMAP, live_port=port, live_poll_s=0.05)
    cfg, tm = load_live(s)
    e = PlantEmulator(tm, seed=9, port=port, health_port=None)
    await e.start()
    clock = FakeClock()
    rt = make_live(tiny, clock, cfg, tm)
    await rt.source.start()
    for _ in range(100):
        if rt.source.ready:
            break
        await asyncio.sleep(0.05)
    assert rt.source.ready

    app = create_app(engine, run_loop=False, live_runtime=rt)
    app.state.hai_dir = Path("/no-hai")
    try:
        with TestClient(app) as c:
            await asyncio.to_thread(c.post, "/api/mode", json={"mode": "live"})
            r = await asyncio.to_thread(
                c.post,
                "/api/attack",
                json={
                    "scenario": "actuator_force",
                    "target": "P101",
                    "magnitude": 0.0,
                    "duration_s": 300,
                },
            )
            assert r.status_code == 200
            attack_id = r.json()["attack_id"]
            t_launch = clock()
            for _ in range(240):
                engine_state = e.plant.state()
                feed(rt.source, engine_state, clock)
                msg = rt.step_sample()
                await e.tick()
                if msg.incident is not None:
                    break
                await asyncio.sleep(0.02)
            assert msg.incident is not None
            assert "P101" in [o.id for o in msg.incident.origin]
            assert msg.incident.ground_truth is not None
            assert msg.incident.ground_truth.attack_id == attack_id
            assert msg.incident.ground_truth.target == "P101"
            assert msg.incident.ground_truth.scenario == "actuator_force"
            assert msg.incident.ground_truth.started_at >= t_launch - 1.0
            assert e.truth and e.truth[0].node_id == "P101"  # the write really happened
    finally:
        await rt.stop()
        await e.stop()


async def test_sim_and_hai_attack_paths_are_unaffected(engine) -> None:  # type: ignore[no-untyped-def]
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = Path("/no-hai")
    with TestClient(app) as c:
        r = c.post(
            "/api/attack",
            json={"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25.0},
        )
        assert r.status_code == 200
        assert engine._attacks.ground_truth()
        c.app.state.mode = "hai"  # type: ignore[attr-defined]
        r = c.post("/api/attack", json={"scenario": "sensor_offset", "target": "LIT101"})
        assert r.status_code == 409 and "HAI" in r.json()["detail"]


async def test_attack_refused_while_live_is_calibrating(
    engine,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    port = free_port()
    s = Settings(
        live_tagmap=TAGMAP,
        live_port=port,
        live_poll_s=0.05,
        live_train_min=99.0,
        models_dir=tmp_path / "models",  # isolated: the real backend/models/live/ must not leak in
    )
    cfg, tm = load_live(s)
    e = PlantEmulator(tm, seed=1, port=port, health_port=None)
    await e.start()
    rt = LiveRuntime(s, cfg, tm, source=LiveSource(cfg, tm))  # no trained model: still calibrating
    await rt.source.start()
    for _ in range(100):
        if rt.source.ready:
            break
        await asyncio.sleep(0.05)
    assert rt.source.ready and rt.engine is None
    app = create_app(engine, run_loop=False, live_runtime=rt)
    app.state.hai_dir = Path("/no-hai")
    try:
        with TestClient(app) as c:
            mode_r = await asyncio.to_thread(c.post, "/api/mode", json={"mode": "live"})
            assert mode_r.status_code == 200 and mode_r.json()["mode"] == "live"
            r = await asyncio.to_thread(
                c.post, "/api/attack", json={"scenario": "sensor_offset", "target": "LIT101"}
            )
            assert r.status_code == 422 and "calibrating" in r.json()["detail"]
    finally:
        await rt.stop()
        await e.stop()


# ----------------------------------------------------- B1a: demo-mode-off blocks before the write
async def test_demo_mode_off_blocks_live_attack_before_the_attacker_is_ever_called(
    tiny: tuple[Loaded, BaselineDetector], engine
) -> None:  # type: ignore[no-untyped-def]
    """`AT_DEMO_MODE=false` must 403 a LIVE attack through `require_demo`, a dependency on the
    route itself, before `post_attack`'s body -- and so before `live_attacker.launch` -- ever
    runs. Checked against the real emulator's own write log (`e.truth`), not a mock call count:
    if the attacker had been invoked at all, this list would be non-empty. A key is supplied so
    `require_key` passes and `require_demo` is the dependency actually under test (Phase 14 B3
    made `require_key` itself fail closed with no key, which is a separate, already-tested path)."""
    port = free_port()
    s = Settings(live_tagmap=TAGMAP, live_port=port, live_poll_s=0.05)
    cfg, tm = load_live(s)
    e = PlantEmulator(tm, seed=9, port=port, health_port=None)
    await e.start()
    clock = FakeClock()
    rt = make_live(tiny, clock, cfg, tm)
    await rt.source.start()
    for _ in range(100):
        if rt.source.ready:
            break
        await asyncio.sleep(0.05)
    assert rt.source.ready

    key = "test-key-123456"
    app = create_app(engine, run_loop=False, live_runtime=rt)
    app.state.hai_dir = Path("/no-hai")
    app.state.settings = Settings(demo_mode=False, api_key=key)  # type: ignore[arg-type]
    try:
        with TestClient(app) as c:
            h = {"X-API-Key": key}
            await asyncio.to_thread(c.post, "/api/mode", json={"mode": "live"}, headers=h)
            r = await asyncio.to_thread(
                c.post,
                "/api/attack",
                json={"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25.0},
                headers=h,
            )
            assert r.status_code == 403 and "Demo mode" in r.json()["detail"]
            assert e.truth == []  # the emulator's own log: nothing was ever written to it
    finally:
        await rt.stop()
        await e.stop()
