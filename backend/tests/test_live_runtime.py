"""Phase 13 Part C: LIVE integration: calibration, quality-aware scoring, persistence, API."""

import asyncio
import copy
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.attacks import Scenario
from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded, load_detector
from app.engine import Engine
from app.evidence import IncidentStore
from app.graph import static_graph
from app.live.config import load_live
from app.live.engine import LiveEngine
from app.live.runtime import LiveRuntime
from app.live.source import LiveSource
from app.live.train import MIN_SAMPLES, LiveRecorder, live_dir, live_models_ready, train_live
from app.main import create_app
from app.schemas import AttackRequest
from app.sim import NODE_IDS
from tests.test_live_engine import FakeClock, feed

TAGMAP = Path(__file__).resolve().parents[2] / "config" / "tagmap.yaml"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def live_settings(tmp_path: Path, **kw: object) -> Settings:
    base: dict[str, object] = {
        "live_tagmap": TAGMAP,
        "live_poll_s": 0.05,
        "models_dir": tmp_path / "models",
        "live_db": tmp_path / "live.sqlite",
    }
    return Settings(**(base | kw))  # type: ignore[arg-type]


def make(
    tiny: tuple[Loaded, BaselineDetector], clock: FakeClock, **kw: object
) -> tuple[LiveEngine, LiveSource]:
    loaded, base = copy.deepcopy(tiny)
    s = Settings(live_tagmap=TAGMAP, live_poll_s=0.05, live_frozen_after_s=3.0, **kw)  # type: ignore[arg-type]
    cfg, tm = load_live(s)
    src = LiveSource(cfg, tm, clock=clock)
    return LiveEngine(loaded, base, static_graph(), s, src, "gdn", clock=clock), src


def clean_states(engine: Engine, n: int) -> list[dict[str, float]]:
    out = []
    for _ in range(n):
        engine.step_sample()
        out.append(engine._plant.state())
    return out


# ------------------------------------------------------------------ quality-aware scoring
def drive(
    live: LiveEngine,
    src: LiveSource,
    clock: FakeClock,
    sim: Engine,
    steps: int,
    tweak: object = None,
) -> list[object]:
    msgs = []
    for _ in range(steps):
        sim.step_sample()
        state = dict(sim._plant.state())
        if callable(tweak):
            state = tweak(state)
        feed(src, state, clock)
        msgs.append(live.step_sample())
    return msgs


def run_fault(
    tiny: tuple[Loaded, BaselineDetector], sim: Engine, include_bad: bool, fault: str
) -> tuple[LiveEngine, list[object]]:
    clock = FakeClock()
    live, src = make(tiny, clock, live_include_bad_quality=include_bad)
    drive(live, src, clock, sim, 60)  # clean warm-up
    assert not live.incidents

    if fault == "stale":  # LIT101 stops updating: its tag is simply not fed any more
        msgs = []
        for _ in range(60):
            sim.step_sample()
            clock.tick()
            state = sim._plant.state()
            for tag in src.tagmap.by_role("value"):
                if tag.node_id != "LIT101":
                    src._on_sample(tag.tag, state[tag.node_id], clock())
            msgs.append(live.step_sample())
        return live, msgs
    if fault == "out_of_range":
        return live, drive(live, src, clock, sim, 60, lambda s: s | {"LIT101": 4000.0})
    raise AssertionError(fault)


@pytest.mark.parametrize("fault", ["stale", "out_of_range"])
def test_a_data_fault_is_not_an_attack(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine, fault: str
) -> None:
    live, msgs = run_fault(tiny, engine, include_bad=False, fault=fault)
    assert live.incidents == []  # masked: no alert, no incident, no false origin
    last = msgs[-1]
    quality = {n.id: n.quality for n in last.nodes}  # type: ignore[attr-defined]
    assert quality["LIT101"] in ("missing", "stale", "out_of_range")
    assert quality["LIT301"] == "good"
    assert live.masked == ["LIT101"]
    assert all(n.status == "normal" for n in last.nodes)  # type: ignore[attr-defined]


@pytest.mark.parametrize("fault", ["stale", "out_of_range"])
def test_the_flag_turns_masking_off(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine, fault: str
) -> None:
    """The control: with AT_LIVE_INCLUDE_BAD_QUALITY the same fault is scored like data."""
    live, _ = run_fault(tiny, engine, include_bad=True, fault=fault)
    assert live.incidents, "the unmasked fault should look like an attack to the detector"
    assert live.incidents[0].origin[0].id == "LIT101"


def test_a_frozen_sensor_is_labelled_but_never_hidden(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine
) -> None:
    """`frozen` is advisory: it must not mask a real freeze attack from detection."""
    clock = FakeClock()
    live, src = make(tiny, clock)
    drive(live, src, clock, engine, 60)
    held = engine._plant.state()["LIT101"]
    msgs = drive(live, src, clock, engine, 40, lambda s: s | {"LIT101": held})  # fresh but constant
    assert any(n.quality == "frozen" for n in msgs[-1].nodes if n.id == "LIT101")  # type: ignore[attr-defined]
    assert live.masked == []  # not neutralised
    assert live.incidents and "LIT101" in [o.id for o in live.incidents[0].origin]


def test_nothing_is_scored_when_the_whole_source_goes_quiet(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine
) -> None:
    clock = FakeClock()
    live, src = make(tiny, clock)
    drive(live, src, clock, engine, 60)
    for _ in range(40):  # the link is down: no new samples at all, time passes
        clock.tick()
        msg = live.step_sample()
    assert live.incidents == []
    assert {n.quality for n in msg.nodes} == {"missing"}


# ------------------------------------------------------------------ trainer
def collect(engine: Engine, n: int) -> object:
    import numpy as np

    rows = []
    for _ in range(n):
        engine.step_sample()
        s = engine._plant.state()
        rows.append([s[k] for k in NODE_IDS])
    return np.array(rows)


def test_training_needs_enough_clean_data(tmp_path: Path) -> None:
    import numpy as np

    with pytest.raises(ValueError, match="at least"):
        train_live(np.zeros((MIN_SAMPLES - 1, 9)), tmp_path)


def test_trainer_splits_by_time_and_sets_the_threshold_from_clean_validation(
    tmp_path: Path, engine: Engine
) -> None:
    x = collect(engine, MIN_SAMPLES)
    meta = train_live(x, tmp_path, epochs=4, log_it=False)  # type: ignore[arg-type]
    assert (meta["train_samples"], meta["val_samples"]) == (480, 120)  # first 80% / last 20%
    assert "clean validation" in str(meta["threshold_rule"])
    assert meta["source"] == "live" and live_models_ready(tmp_path)
    assert meta["init"] == "scratch"  # no SIM models in this folder to start from
    loaded = load_detector(live_dir(tmp_path))
    models = meta["models"]
    assert loaded.threshold == pytest.approx(models[str(meta["active"])]["threshold"])  # type: ignore[index]
    assert len(loaded.node_thr) == 9


@pytest.mark.skipif(
    not Path("models/detector.json").exists(), reason="needs the trained SIM models"
)
def test_trainer_starts_from_the_sim_weights_when_they_exist(
    tmp_path: Path, engine: Engine
) -> None:
    x = collect(engine, MIN_SAMPLES)
    sim = Path("models")
    meta = train_live(x, tmp_path, sim_models_dir=sim, log_it=False)  # type: ignore[arg-type]
    assert meta["init"] == "sim-weights"
    sim_meta = json.loads((sim / "detector.json").read_text())
    assert meta["norm"] == sim_meta["norm"]  # same normalization: the weights stay meaningful
    cold = train_live(
        x, tmp_path / "cold", sim_models_dir=tmp_path / "none", epochs=4, log_it=False
    )  # type: ignore[arg-type]
    assert cold["init"] == "scratch"
    assert meta["models"]["mlp"]["val_mse"] < cold["models"]["mlp"]["val_mse"]  # type: ignore[index]


def test_the_recorder_keeps_only_clean_complete_snapshots(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine
) -> None:
    clock = FakeClock()
    _, src = make(tiny, clock)
    rec = LiveRecorder(10)
    feed(src, engine._plant.state(), clock)
    assert rec.add(src.snapshot(clock()))
    clock.tick(2.0)  # everything is stale now
    assert not rec.add(src.snapshot(clock()))
    assert (len(rec.rows), rec.skipped) == (1, 1) and rec.progress == pytest.approx(0.1)


# ------------------------------------------------------------------ calibrating -> running
async def test_calibrating_has_progress_no_alerts_and_then_runs(
    tmp_path: Path, engine: Engine
) -> None:
    s = live_settings(tmp_path, live_train_min=5.0)  # 600 samples: the smallest honest recording
    cfg, tm = load_live(s)
    clock = FakeClock()
    src = LiveSource(cfg, tm, clock=clock)
    rt = LiveRuntime(s, cfg, tm, source=src, clock=clock)
    src.poller.state = "connected"  # samples are injected; no socket in this test
    assert rt.engine is None and rt.phase == "waiting"
    msg = rt.step_sample()  # nothing read yet: data-less but valid, no alert
    assert msg.mode == "live" and msg.alert is None and msg.incident is None

    seen = []
    for i in range(MIN_SAMPLES):
        engine.step_sample()
        feed(src, engine._plant.state(), clock)
        msg = rt.step_sample()
        assert msg.alert is None and msg.incident is None  # no alerts while calibrating
        if i in (0, 299):
            seen.append(rt.source_info())
    assert seen[0].state == "calibrating" and 0.0 < (seen[0].progress or 0) < 0.1
    assert (seen[1].progress or 0) > 0.45
    assert rt._training is not None
    await rt._training  # trains on the recording just made
    assert rt.engine is not None and rt.phase == "running" and live_models_ready(s.models_dir)
    assert rt.detector_kind in ("gdn", "mlp")
    assert rt.train_error is None
    engine.step_sample()
    feed(src, engine._plant.state(), clock)
    nxt = rt.step_sample()
    assert nxt.nodes[0].quality == "good" and nxt.mode == "live"


# ------------------------------------------------------------------ persistence
def test_incidents_survive_a_restart_and_ids_continue(
    tiny: tuple[Loaded, BaselineDetector], engine: Engine, tmp_path: Path
) -> None:
    s = live_settings(tmp_path)
    cfg, tm = load_live(s)
    clock = FakeClock()
    live, src = make(tiny, clock)
    rt = LiveRuntime(s, cfg, tm, source=src, store=IncidentStore(s.live_db))
    rt.engine = live  # a model-free stand-in for the trained one
    for _ in range(60):
        engine.step_sample()
        feed(src, engine._plant.state(), clock)
        rt.step_sample()
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300))
    for _ in range(40):
        engine.step_sample()
        feed(src, engine._plant.state(), clock)
        rt.step_sample()
    assert len(rt.incidents) == 1 and rt.incidents[0].status in ("localizing", "open")
    before = rt.incidents[0]
    assert before.mode == "live"
    assert rt.store is not None
    rt.store.close()

    store2 = IncidentStore(s.live_db)  # the process restarts
    again = store2.load()
    assert [i.id for i in again] == [before.id]
    assert again[0].origin == before.origin and again[0].path == before.path
    assert again[0].origin[0].breakdown is not None  # the score breakdown is stored too
    assert again[0].status == "closed"  # it was running when the process stopped
    rt2 = LiveRuntime(s, cfg, tm, source=LiveSource(cfg, tm, clock=clock), store=store2)
    assert [i.id for i in rt2.incidents] == [before.id]
    live2, _ = make(tiny, clock)
    live2.incidents = list(rt2.incidents)
    assert f"inc_{len(live2.incidents) + 1:03d}" == "inc_002"  # new ids do not collide


def test_store_only_returns_its_own_mode(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    assert store.load("live") == [] and store.load("sim") == []
    store.close()


# ------------------------------------------------------------------ API
@pytest.fixture
async def emulator_runtime(tmp_path: Path):  # type: ignore[no-untyped-def]
    from plant_emulator.server import PlantEmulator

    port = free_port()
    s = live_settings(tmp_path, live_port=port, live_train_min=30.0)
    cfg, tm = load_live(s)
    emu = PlantEmulator(tm, seed=5, port=port, health_port=None)
    await emu.start()
    rt = LiveRuntime(s, cfg, tm, store=IncidentStore(s.live_db))
    await rt.source.start()
    for _ in range(100):
        if rt.source.ready and rt.available()[0]:
            break
        await asyncio.sleep(0.05)
    yield rt, emu, tm, port
    await rt.stop()
    await emu.stop()


def test_live_is_unavailable_without_a_source_and_never_crashes(
    engine: Engine, tmp_path: Path
) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["live_available"] is False and st["live_reason"]
        assert st["source"]["mode"] == "sim" and st["source"]["protocol"] == "internal"
        r = c.post("/api/mode", json={"mode": "live"})
        assert r.status_code == 409 and "LIVE unavailable" in r.json()["detail"]
        assert c.get("/api/status").json()["mode"] == "sim"  # still SIM
        assert c.get("/api/live/health").status_code == 404


async def test_switching_to_live_serves_quality_health_and_stays_read_only(
    engine: Engine,
    tmp_path: Path,
    emulator_runtime,  # type: ignore[no-untyped-def]
) -> None:
    rt, emu = emulator_runtime[0], emulator_runtime[1]
    app = create_app(engine, run_loop=False, live_runtime=rt)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        assert c.get("/api/status").json()["live_available"] is True
        st = c.post("/api/mode", json={"mode": "live"}).json()
        assert st["mode"] == "live" and st["source"]["protocol"] == "modbus"
        assert st["source"]["state"] == "calibrating" and st["source"]["progress"] is not None
        rt.step_sample()  # the loop does this twice a second
        health = c.get("/api/live/health").json()
        assert len(health) == 9 and {h["quality"] for h in health} == {"good"}
        assert {"tag", "node_id", "quality", "age_ms", "last_value"} <= set(health[0])
        with c.websocket_connect("/ws/live") as ws:
            msg = ws.receive_json()
        assert msg["mode"] == "live" and msg["alert"] is None
        assert {n["quality"] for n in msg["nodes"]} == {"good"}
        assert msg["source_latency_ms"] is not None and msg["source_latency_ms"] < 1000
        assert all(n["truth"] is None for n in msg["nodes"])
        # Isolate in LIVE is advice only: 409 live-read-only, nothing written anywhere.
        r = c.post("/api/isolate", json={"incident_id": "inc_001", "node_id": "P101"})
        assert r.status_code == 409
        body = r.json()
        assert body["reason"] == "live-read-only" and body["accepted"] is False and body["advice"]
        # An attack in LIVE never reaches the simulator's engine. This LIVE runtime has no
        # trained detector (the emulator_runtime fixture never records a clean minutes' worth),
        # so the attacker module is never even reached.
        r = c.post("/api/attack", json={"scenario": "sensor_offset", "target": "LIT101"})
        assert r.status_code == 422 and "calibrating" in r.json()["detail"]
        assert engine._attacks.ground_truth() == []
        # Back to SIM works.
        assert c.post("/api/mode", json={"mode": "sim"}).json()["mode"] == "sim"
    assert emu.truth == []  # AttackTrace wrote nothing to the emulated plant


async def test_a_source_that_goes_away_shows_down_not_a_crash(
    engine: Engine,
    tmp_path: Path,
    emulator_runtime,  # type: ignore[no-untyped-def]
) -> None:
    rt, emu = emulator_runtime[0], emulator_runtime[1]
    app = create_app(engine, run_loop=False, live_runtime=rt)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        c.post("/api/mode", json={"mode": "live"})
        await emu.stop()
        for _ in range(100):
            if not rt.source.status().connected:
                break
            await asyncio.sleep(0.05)
        rt.step_sample()
        st = c.get("/api/status").json()
        assert st["mode"] == "live" and st["source"]["state"] in ("down", "stale", "connecting")
        assert st["source"]["connected"] is False and st["source"]["reason"]
        assert c.get("/api/live/health").status_code == 200  # still answers, with ages
