"""Phase 13 Part A: tag map and plant emulator (real Modbus TCP over loopback, no hardware)."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from plant_emulator.server import PlantEmulator
from pydantic import ValidationError
from pymodbus.client import AsyncModbusTcpClient

from app.live.tagmap import TagMap, TagMapError, decode, encode, load_tagmap

REPO = Path(__file__).resolve().parents[2]
TAGMAP = REPO / "config" / "tagmap.yaml"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ------------------------------------------------------------------------------- tag map
def raw_map() -> dict[str, Any]:
    return yaml.safe_load(TAGMAP.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_shipped_tagmap_is_valid_and_complete() -> None:
    tm = load_tagmap(TAGMAP)
    assert len(tm.by_role("value")) == 9
    assert {t.node_id for t in tm.by_role("value")} == {
        "LIT101", "FIT201", "PIT301", "LIT301", "MV101", "P101", "P301", "PLC1", "PLC2",
    }  # fmt: skip
    assert all(t.access == "ro" and t.table == "input" for t in tm.by_role("value"))
    assert all(t.access == "rw" and t.table == "holding" for t in tm.tags if t.role != "value")
    assert list(tm.blocks("input")) == [(0, 24)]  # one request reads every process value


def mutate(fn: Any) -> dict[str, Any]:
    data = raw_map()
    fn(data)
    return data


BAD = {
    "duplicate tag": lambda d: d["tags"].append(dict(d["tags"][0])),
    "overlap": lambda d: d["tags"][1].update(address=1),
    "missing node": lambda d: d["tags"].pop(8),
    "force on a sensor": lambda d: d["tags"][9].update(role="force"),
    "input must be ro": lambda d: d["tags"][0].update(access="rw"),
    "holding must be rw": lambda d: d["tags"][9].update(access="ro"),
    "min above max": lambda d: d["tags"][0].update(min=10, max=1),
    "zero scale": lambda d: d["tags"][0].update(scale=0),
    "unknown field": lambda d: d["tags"][0].update(extra=1),
    "unknown protocol": lambda d: d["tags"][0].update(protocol="s7"),
    "address out of range": lambda d: d["tags"][0].update(address=70000),
    "wrong version": lambda d: d.update(version=2),
    "freeze must be int16": lambda d: d["tags"][13].update(type="float32"),
}


@pytest.mark.parametrize("name", list(BAD))
def test_invalid_tagmaps_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        TagMap.model_validate(mutate(BAD[name]))


def test_load_reports_readable_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("tags: [unclosed", encoding="utf-8")
    with pytest.raises(TagMapError, match="not valid YAML"):
        load_tagmap(broken)
    with pytest.raises(TagMapError, match="cannot read"):
        load_tagmap(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(mutate(BAD["overlap"])), encoding="utf-8")
    with pytest.raises(TagMapError, match="overlaps"):
        load_tagmap(bad)


def test_encoding_round_trips() -> None:
    tm = load_tagmap(TAGMAP)
    lit, freeze = tm.get("LIT101"), tm.get("LIT101.spoof_freeze")
    assert decode(lit, encode(lit, 53.25)) == 53.25
    assert decode(lit, encode(lit, -0.5)) == -0.5
    assert decode(freeze, encode(freeze, 1)) == 1
    assert decode(freeze, [0xFFFF]) == -1  # int16 is signed


# ------------------------------------------------------------------------------- emulator
@pytest.fixture
async def emu() -> AsyncIterator[PlantEmulator]:
    e = PlantEmulator(
        load_tagmap(TAGMAP), seed=42, port=free_port(), health_port=None, realtime=False
    )
    await e.start()
    yield e
    await e.stop()


async def client_for(e: PlantEmulator) -> AsyncModbusTcpClient:
    c = AsyncModbusTcpClient("127.0.0.1", port=e.port)
    await c.connect()
    assert c.connected
    return c


async def read_values(c: AsyncModbusTcpClient, e: PlantEmulator) -> dict[str, float]:
    rr = await c.read_input_registers(0, count=e.tagmap.size("input"), device_id=1)
    assert not rr.isError()
    return {
        t.node_id: decode(t, rr.registers[t.address : t.address + t.width])
        for t in e.tagmap.by_role("value")
    }


async def write(c: AsyncModbusTcpClient, e: PlantEmulator, tag: str, value: float) -> None:
    t = e.tagmap.get(tag)
    rr = await c.write_registers(t.address, encode(t, value), device_id=1)
    assert not rr.isError()


async def run_ticks(e: PlantEmulator, n: int) -> None:
    for _ in range(n):
        await e.tick()


async def test_registers_track_the_model(emu: PlantEmulator) -> None:
    c = await client_for(emu)
    await run_ticks(emu, 30)
    seen = await read_values(c, emu)
    state = emu.plant.state()
    assert set(seen) == set(state)
    for node, value in seen.items():
        assert value == pytest.approx(state[node], rel=1e-5, abs=1e-5), node
    await run_ticks(emu, 30)  # and they keep following it
    again = await read_values(c, emu)
    assert again != seen
    for node, value in again.items():
        assert value == pytest.approx(emu.plant.state()[node], rel=1e-5, abs=1e-5), node
    c.close()


async def test_clients_cannot_write_process_values(emu: PlantEmulator) -> None:
    c = await client_for(emu)
    t = emu.tagmap.get("LIT101")
    rr = await c.write_registers(
        t.address, encode(t, 99.0), device_id=1
    )  # holding table, not input
    await run_ticks(emu, 5)
    assert (await read_values(c, emu))["LIT101"] != pytest.approx(99.0, abs=1.0)
    assert rr is not None
    c.close()


async def twin_run(seed: int, ticks: int, writes: dict[str, float]) -> PlantEmulator:
    e = PlantEmulator(
        load_tagmap(TAGMAP), seed=seed, port=free_port(), health_port=None, realtime=False
    )
    await e.start()
    try:
        c = await client_for(e)
        await run_ticks(e, 50)
        for tag, v in writes.items():
            await write(c, e, tag, v)
        await run_ticks(e, ticks)
        c.close()
    finally:
        await e.stop()
    return e


async def test_forcing_a_pump_off_changes_the_plant() -> None:
    clean = await twin_run(7, 600, {})
    attacked = await twin_run(7, 600, {"P101.force": 0.0})
    assert attacked.plant.actual["P101"] < 0.05  # the pump really stopped
    assert attacked.plant.l1 > clean.plant.l1 + 5.0  # so T1 filled up


async def test_a_sensor_offset_fools_the_controller() -> None:
    clean = await twin_run(7, 400, {})
    attacked = await twin_run(7, 400, {"LIT101.spoof_offset": -25.0})
    # The SCADA value reads low while the controller drives the real tank up.
    assert attacked.plant.state()["LIT101"] < attacked.plant.physical_truth()["LIT101"] - 15.0
    assert attacked.plant.l1 > clean.plant.l1 + 8.0


async def test_a_rogue_setpoint_moves_the_plant() -> None:
    clean = await twin_run(7, 800, {})
    attacked = await twin_run(7, 800, {"PLC1.setpoint_delta": 20.0})
    assert attacked.plant.setpoints["PLC1"] == pytest.approx(70.0)
    assert attacked.plant.l1 > clean.plant.l1 + 5.0


async def test_freeze_holds_the_reading_and_release_resumes_it(emu: PlantEmulator) -> None:
    c = await client_for(emu)
    await run_ticks(emu, 20)
    await write(c, emu, "FIT201.spoof_freeze", 1)
    await run_ticks(emu, 5)
    held = [(await read_values(c, emu))["FIT201"]]
    for _ in range(30):
        await run_ticks(emu, 1)
        held.append((await read_values(c, emu))["FIT201"])
    assert len(set(held[1:])) == 1  # constant while frozen
    await write(c, emu, "FIT201.spoof_freeze", 0)
    await run_ticks(emu, 20)
    after = {(await read_values(c, emu))["FIT201"] for _ in range(1)}
    assert after != {held[-1]}
    c.close()


async def test_ground_truth_is_recorded_from_the_registers(emu: PlantEmulator) -> None:
    c = await client_for(emu)
    await run_ticks(emu, 10)
    assert emu.truth == []
    await write(c, emu, "LIT301.spoof_offset", 12.0)
    await run_ticks(emu, 3)
    assert [(e.node_id, e.scenario) for e in emu.truth] == [("LIT301", "sensor_offset")]
    assert emu.truth[0].end_wall is None
    await write(c, emu, "LIT301.spoof_offset", 0.0)
    await run_ticks(emu, 3)
    assert emu.truth[0].end_wall is not None
    await write(c, emu, "MV101.force", 1.0)
    await run_ticks(emu, 2)
    assert emu.truth[-1].scenario == "actuator_force"
    c.close()


async def test_force_registers_start_at_no_override(emu: PlantEmulator) -> None:
    c = await client_for(emu)
    for tag in emu.tagmap.by_role("force"):
        rr = await c.read_holding_registers(tag.address, count=tag.width, device_id=1)
        assert decode(tag, rr.registers) == -1.0
    await run_ticks(emu, 5)
    assert emu.truth == []  # -1 is "no override", not an attack
    c.close()


async def test_real_time_loop_health_and_clean_shutdown() -> None:
    port, hport = free_port(), free_port()
    e = PlantEmulator(load_tagmap(TAGMAP), port=port, health_port=hport, hz=10.0)
    await e.start()
    await asyncio.sleep(1.6)
    reader, writer = await asyncio.open_connection("127.0.0.1", hport)
    writer.write(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    raw = await reader.read()
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200")
    health = json.loads(body)
    assert health["status"] == "ok" and health["ticks"] >= 10
    assert health["hz_measured"] is not None and 5.0 < health["hz_measured"] < 15.0
    for path, code in ((b"/truth", b"200"), (b"/nope", b"404")):
        r, w = await asyncio.open_connection("127.0.0.1", hport)
        w.write(b"GET " + path + b" HTTP/1.1\r\n\r\n")
        assert (await r.read()).split(b"\r\n")[0].split()[1] == code
        w.close()
    await e.stop()
    await e.stop()  # idempotent
    for p in (port, hport):  # both ports are free again
        with socket.socket() as s:
            s.bind(("127.0.0.1", p))
    leftovers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert all(t.done() or t.cancelled() for t in leftovers if "serve_forever" in repr(t))


async def test_stop_before_start_is_safe() -> None:
    e = PlantEmulator(load_tagmap(TAGMAP), port=free_port(), health_port=None, realtime=False)
    await e.stop()
