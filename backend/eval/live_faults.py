"""Phase 13 Part F: fault-injection checks against the real stack (own, short-lived emulator).

Three checks, each against a running `LiveEngine` + `LiveSource`:
  1. emulator down -> source reports `down`, no exception, no false origin.
  2. a slow network (simulated: every read is delayed) -> quality `stale`, no exception.
  3. a corrupted out-of-range register value -> quality `out_of_range`, excluded from the origin
     ranking (never shown as a false origin).

Writes `reports/live_faults.json`. Independent of `eval.live`/`eval.live_soak`: it spawns its own
emulator on a free port, so it can run before, after, or instead of them.
"""

import asyncio
import json
import logging
import socket
import sys
import time
import traceback
from pathlib import Path

try:
    import attacker  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings, get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.graph import load_graph
from app.live.config import load_live
from app.live.engine import LiveEngine
from app.live.modbus import ReadOnlyClient
from app.live.source import LiveSource
from app.live.train import live_dir, live_models_ready
from eval.live_soak import spawn_emulator, wait_healthy

log = logging.getLogger("attacktrace.eval.live_faults")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class SlowClient:
    """Wraps a real `ReadOnlyModbus` and adds a fixed delay before every read: a simulated
    slow/congested network, exercised through the exact production read path."""

    def __init__(self, inner: ReadOnlyClient, delay_s: float) -> None:
        self._inner, self._delay_s = inner, delay_s

    @property
    def connected(self) -> bool:
        return self._inner.connected

    async def connect(self) -> bool:
        return await self._inner.connect()

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        await asyncio.sleep(self._delay_s)
        return await self._inner.read_input_registers(address, count)

    async def close(self) -> None:
        await self._inner.close()


async def build_engine(settings: Settings, port: int) -> tuple[LiveEngine, LiveSource]:
    cfg, tagmap = load_live(Settings(**{**settings.model_dump(), "live_port": port}))
    d = live_dir(settings.models_dir)
    kind = str(json.loads((d / "detector.json").read_text())["active"])
    source = LiveSource(cfg, tagmap)
    engine = LiveEngine(
        load_detector(d), load_baseline(d), load_graph(d / "graph.json"), settings, source, kind
    )
    return engine, source


async def check_emulator_down(settings: Settings) -> dict[str, object]:
    port, health_port = _free_port(), _free_port()
    emu = spawn_emulator(port, health_port, settings.seed)
    exceptions: list[str] = []
    try:
        assert await wait_healthy(health_port, 20.0), "emulator never came up"
        engine, source = await build_engine(settings, port)
        await source.start()
        for _ in range(60):
            if source.ready:
                break
            await asyncio.sleep(0.2)
        assert source.ready, "source never became ready before the kill"

        emu.kill()
        emu.wait(timeout=10)
        for _ in range(20):  # up to ~10 s for the poller to notice and mark it down
            try:
                engine.step_sample()
            except Exception:
                exceptions.append(traceback.format_exc())
            if source.status().state == "down":
                break
            await asyncio.sleep(0.5)
        final = source.status()
        await source.stop()
        return {
            "final_state": final.state,
            "connected": final.connected,
            "reason": final.reason,
            "exceptions": exceptions,
            "pass": final.state == "down" and not final.connected and not exceptions,
        }
    finally:
        emu.kill()


async def check_slow_network(settings: Settings) -> dict[str, object]:
    port, health_port = _free_port(), _free_port()
    emu = spawn_emulator(port, health_port, settings.seed)
    exceptions: list[str] = []
    try:
        assert await wait_healthy(health_port, 20.0), "emulator never came up"
        cfg, tagmap = load_live(Settings(**{**settings.model_dump(), "live_port": port}))
        d = live_dir(settings.models_dir)
        kind = str(json.loads((d / "detector.json").read_text())["active"])
        source = LiveSource(cfg, tagmap, client_factory=None)
        # Every poller connection it opens is wrapped with an extra delay well past
        # `stale_after_s`, simulating a slow/congested network through the real read path.
        from app.live.modbus import ReadOnlyModbus

        delay_s = cfg.stale_after_s + 1.0

        def slow_factory() -> ReadOnlyClient:
            return SlowClient(
                ReadOnlyModbus(cfg.host, cfg.port, cfg.timeout_s, tagmap.device_id), delay_s
            )

        source.poller._factory = slow_factory
        engine = LiveEngine(
            load_detector(d), load_baseline(d), load_graph(d / "graph.json"), settings, source, kind
        )
        await source.start()
        for _ in range(60):
            if source.ready:
                break
            await asyncio.sleep(0.5)
        assert source.ready, "source never became ready even once (unexpected)"

        qualities: list[str] = []
        deadline = time.monotonic() + delay_s + cfg.stale_after_s + 8.0
        while time.monotonic() < deadline:
            try:
                engine.step_sample()
            except Exception:
                exceptions.append(traceback.format_exc())
            snap = source.snapshot()
            qualities.append(next(iter(snap.quality.values())))
            if "stale" in qualities or "missing" in qualities:
                break
            await asyncio.sleep(0.5)
        await source.stop()
        return {
            "qualities_seen": sorted(set(qualities)),
            "exceptions": exceptions,
            "pass": ("stale" in qualities or "missing" in qualities) and not exceptions,
        }
    finally:
        emu.kill()


async def check_out_of_range(settings: Settings) -> dict[str, object]:
    """Modbus has no write access to input registers at all (function code 16 only ever reaches
    holding registers, whatever address is given — `test_clients_cannot_write_process_values` in
    `tests/test_emulator.py` checks exactly this), so the only way any client, including this
    one, can push LIT101's published reading out of range is the emulator's own spoof-offset
    path, driven far past any real attack magnitude. The engine sees the same corrupted input
    register either way; this exercises the identical masking code a true sensor fault would hit.
    """
    from attacker.client import AttackerClient

    from app.attacks.engine import Scenario

    port, health_port = _free_port(), _free_port()
    emu = spawn_emulator(port, health_port, settings.seed)
    exceptions: list[str] = []
    try:
        assert await wait_healthy(health_port, 20.0), "emulator never came up"
        engine, source = await build_engine(settings, port)
        await source.start()
        for _ in range(60):
            if source.ready:
                break
            await asyncio.sleep(0.2)
        assert source.ready

        cfg, tagmap = load_live(Settings(**{**settings.model_dump(), "live_port": port}))
        atk = AttackerClient(cfg.host, cfg.port, tagmap, settings.attacker_allowlist)
        assert await atk.connect()
        await atk.launch(Scenario.SENSOR_OFFSET, "LIT101", 1.0e6, 20.0)

        quality = "good"
        origin_id: str | None = None
        for _ in range(16):
            try:
                msg = engine.step_sample()
            except Exception:
                exceptions.append(traceback.format_exc())
                await asyncio.sleep(0.5)
                continue
            lit = next(n for n in msg.nodes if n.id == "LIT101")
            quality = lit.quality or quality
            if msg.incident is not None and msg.incident.origin:
                origin_id = msg.incident.origin[0].id
            await asyncio.sleep(0.5)
        await atk.close()
        await source.stop()
        return {
            "final_quality": quality,
            "origin_was_the_corrupted_node": origin_id == "LIT101",
            "exceptions": exceptions,
            "pass": quality == "out_of_range" and origin_id != "LIT101" and not exceptions,
        }
    finally:
        emu.kill()


async def main_async() -> dict[str, object]:
    settings = get_settings()
    if not live_models_ready(settings.models_dir):
        raise SystemExit("no LIVE model: run `make live-train` first")
    log.info("check 1/3: emulator down")
    down = await check_emulator_down(settings)
    log.info("check 2/3: slow network")
    slow = await check_slow_network(settings)
    log.info("check 3/3: corrupted out-of-range value")
    bad = await check_out_of_range(settings)
    return {"emulator_down": down, "slow_network": slow, "out_of_range": bad}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    result = asyncio.run(main_async())
    settings = get_settings()
    out = settings.reports_dir / "live_faults.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    ok = all(bool(v["pass"]) for v in result.values())  # type: ignore[index]
    log.info("wrote %s: all passed=%s", out, ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
