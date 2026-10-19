"""Phase 13 Part B: the SIM engine running on a LIVE source (same code path, different data)."""

import asyncio
import copy
import time
from pathlib import Path

import pytest

from app.attacks import Scenario
from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.graph import static_graph
from app.live.config import load_live
from app.live.engine import LIVE_READ_ONLY, LiveEngine
from app.live.source import LiveSource, SourceNotReadyError
from app.live.tagmap import encode
from app.schemas import AttackRequest, LiveMessage
from app.sim import NODE_IDS

TAGMAP = Path(__file__).resolve().parents[2] / "config" / "tagmap.yaml"


class FakeClock:
    """Advances only when told to, so tests do not depend on the wall clock's resolution."""

    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float = 0.5) -> None:
        self.t += dt


def make_live(
    tiny: tuple[Loaded, BaselineDetector], clock: FakeClock | None = None
) -> tuple[LiveEngine, LiveSource]:
    # Own copy of the detector: a streaming detector holds state, two engines must not share one.
    loaded, base = copy.deepcopy(tiny)
    cfg, tm = load_live(Settings(live_tagmap=TAGMAP, live_poll_s=0.05))
    clock = clock or FakeClock()
    src = LiveSource(cfg, tm, clock=clock)
    engine = LiveEngine(
        loaded, base, static_graph(), Settings(), src, detector_kind="gdn", clock=clock
    )
    return engine, src


def feed(src: LiveSource, state: dict[str, float], clock: FakeClock) -> None:
    clock.tick()
    for tag in src.tagmap.by_role("value"):
        src._on_sample(tag.tag, state[tag.node_id], clock())


def test_live_messages_have_the_same_schema_as_sim(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine
) -> None:
    sim = engine.step_sample()
    clock = FakeClock()
    live_engine, src = make_live(tiny, clock)
    feed(src, {n.id: n.value for n in sim.nodes}, clock)
    live = live_engine.step_sample()
    assert set(live.model_dump()) == set(sim.model_dump())
    assert [n.id for n in live.nodes] == [n.id for n in sim.nodes] == list(NODE_IDS)
    assert set(live.nodes[0].model_dump()) == set(sim.nodes[0].model_dump())
    assert live.mode == "live" and sim.mode == "sim"
    assert all(n.truth is None for n in live.nodes)  # a live plant has no physical truth
    assert live.impact is None and live.incident is None
    assert LiveMessage.model_validate(live.model_dump()) == live  # valid against the contract


def test_the_engine_waits_for_the_first_reading(tiny: tuple[Loaded, BaselineDetector]) -> None:
    live_engine, _ = make_live(tiny)
    with pytest.raises(SourceNotReadyError):
        live_engine.step_sample()


def test_live_is_read_only_toward_the_plant(tiny: tuple[Loaded, BaselineDetector]) -> None:
    live_engine, _ = make_live(tiny)
    assert live_engine.isolate("inc_001", "P101") == (False, LIVE_READ_ONLY)
    with pytest.raises(ValueError, match="attacker"):
        live_engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))


def test_a_sim_attack_is_found_through_the_live_path(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine
) -> None:
    """Values from an attacked plant go in through LiveSource; the unchanged engine localizes."""
    clock = FakeClock()
    live_engine, src = make_live(tiny, clock)
    for _ in range(60):
        engine.step_sample()
        feed(src, engine._plant.state(), clock)
        live_engine.step_sample()
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300))
    worst = 0.0
    for _ in range(80):
        engine.step_sample()
        feed(src, engine._plant.state(), clock)
        t0 = time.perf_counter()
        live_engine.step_sample()
        worst = max(worst, time.perf_counter() - t0)
    assert live_engine.incidents, "no incident on the live path"
    assert "P101" in [o.id for o in live_engine.incidents[0].origin]
    assert worst < 1.0  # decision latency


# ----------------------------------------------------------------- real protocol, real time
async def test_end_to_end_with_the_emulator(tiny: tuple[Loaded, BaselineDetector]) -> None:
    """Emulator (Modbus TCP) -> poller -> LiveSource -> LiveEngine, in real time. A rogue register
    write forces the transfer pump off; the engine must raise an incident that names P101."""
    import socket

    from plant_emulator.server import PlantEmulator

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    cfg, tm = load_live(Settings(live_tagmap=TAGMAP, live_port=port, live_poll_s=0.1))
    emu = PlantEmulator(tm, seed=11, port=port, health_port=None)
    await emu.start()
    loaded, base = tiny
    src = LiveSource(cfg, tm)
    engine = LiveEngine(loaded, base, static_graph(), Settings(), src, detector_kind="gdn")
    await src.start()
    from pymodbus.client import AsyncModbusTcpClient

    attacker = AsyncModbusTcpClient("127.0.0.1", port=port)
    await attacker.connect()
    try:
        for _ in range(100):
            if src.ready:
                break
            await asyncio.sleep(0.1)
        assert src.ready
        found = None
        worst = 0.0
        t_attack = None
        for k in range(120):  # at most 60 s of 2 Hz ticks
            if k == 24:  # after 12 s of clean data
                force = tm.get("P101.force")
                await attacker.write_registers(force.address, encode(force, 0.0), device_id=1)
                t_attack = time.time()
            t0 = time.perf_counter()
            msg = engine.step_sample()
            worst = max(worst, time.perf_counter() - t0)
            if msg.incident and k >= 24:
                found = msg.incident
                break
            await asyncio.sleep(0.5)
        assert found is not None, "no incident within 60 s"
        assert "P101" in [o.id for o in found.origin]
        assert worst < 1.0
        assert t_attack is not None and found.detected_at >= t_attack
        assert src.status().connected and src.status().latency_ms_p95 is not None
        assert emu.truth and emu.truth[0].node_id == "P101"  # ground truth lives in the emulator
    finally:
        attacker.close()
        await src.stop()
        await emu.stop()
