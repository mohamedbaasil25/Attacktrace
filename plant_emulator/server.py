"""The plant emulator: the simulator's physics behind a Modbus TCP server, in its own process.

Sensors, actuator positions and PLC outputs are published in input registers; the attack surface
(spoof offsets and freezes, forced actuator commands, setpoint deltas) is in holding registers
that any client may write. Each tick (10 Hz, wall clock) the emulator reads those registers into
the overlay, steps the plant, and publishes the new values. Ground truth is recorded from the
registers themselves, so it cannot be claimed by an attacker, only caused.
"""

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from app.live.tagmap import Role, Tag, TagMap, decode, encode
from app.sim import Plant
from plant_emulator.overlay import RegisterOverlay

HOLDING_FC = 3
INPUT_FC = 4
KIND = {
    "spoof_offset": "sensor_offset",
    "spoof_freeze": "sensor_freeze",
    "force": "actuator_force",
    "setpoint_delta": "rogue_setpoint",
}


@dataclass
class TruthEvent:
    """One attack surface in use, observed on the registers."""

    id: str
    node_id: str
    tag: str
    role: str
    scenario: str  # inferred from the register; the attacker may refine it
    start_wall: float
    start_plant_t: float
    end_wall: float | None = None


class PlantEmulator:
    def __init__(
        self,
        tagmap: TagMap,
        seed: int = 42,
        host: str = "127.0.0.1",
        port: int = 5020,
        health_port: int | None = 8081,
        hz: float = 10.0,
        realtime: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.tagmap, self.seed, self.host, self.port = tagmap, seed, host, port
        self.health_port, self.hz, self.realtime, self._clock = health_port, hz, realtime, clock
        self.overlay = RegisterOverlay()
        self.plant = Plant(seed=seed, overlay=self.overlay, track_impact=False)
        self.ticks = 0
        self.truth: list[TruthEvent] = []
        self._active: dict[tuple[str, str], TruthEvent] = {}
        self._lag_ms: deque[float] = deque(maxlen=600)
        self._tick_wall: deque[float] = deque(maxlen=101)
        self._server: ModbusTcpServer | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._health: asyncio.Server | None = None

    # ------------------------------------------------------------------ lifecycle
    def _device(self) -> SimDevice:
        n_in, n_hold = self.tagmap.size("input"), self.tagmap.size("holding")
        co = [SimData(0, count=1, values=False, datatype=DataType.BITS)]
        di = [SimData(0, count=1, values=False, datatype=DataType.BITS)]
        hr = [SimData(0, count=n_hold, values=0, datatype=DataType.REGISTERS)]
        ir = [SimData(0, count=n_in, values=0, datatype=DataType.REGISTERS)]
        return SimDevice(self.tagmap.device_id, simdata=(co, di, hr, ir))

    async def start(self) -> None:
        self._server = ModbusTcpServer(self._device(), address=(self.host, self.port))
        self._tasks.append(asyncio.create_task(self._server.serve_forever()))
        for _ in range(100):  # wait until the socket accepts connections
            if self._server.is_active():
                break
            await asyncio.sleep(0.02)
        for tag in self.tagmap.by_role("force"):  # -1 = no override
            await self._set(HOLDING_FC, tag, -1.0)
        await self._publish()
        if self.health_port is not None:
            self._health = await asyncio.start_server(
                self._handle_http, self.host, self.health_port
            )
        if self.realtime:
            self._tasks.append(asyncio.create_task(self._run()))

    async def stop(self) -> None:
        """Cancel the loop, close both servers and wait for every task; the ports are free after."""
        for task in self._tasks:
            task.cancel()
        if self._health is not None:
            self._health.close()
            await self._health.wait_closed()
            self._health = None
        if self._server is not None:
            await self._server.shutdown()  # type: ignore[no-untyped-call]
            self._server = None
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------ registers
    @property
    def server(self) -> ModbusTcpServer:
        if self._server is None:
            raise RuntimeError("emulator is not started")
        return self._server

    async def _set(self, fc: int, tag: Tag, value: float) -> None:
        await self.server.async_setValues(
            self.tagmap.device_id, fc, tag.address, encode(tag, value)
        )

    async def _get(self, fc: int, tag: Tag) -> float:
        regs = await self.server.async_getValues(self.tagmap.device_id, fc, tag.address, tag.width)
        return decode(tag, [int(r) for r in regs])

    async def _publish(self) -> None:
        state = self.plant.state()
        for tag in self.tagmap.by_role("value"):
            await self._set(INPUT_FC, tag, state[tag.node_id])

    async def _read_controls(self) -> None:
        c = self.overlay.controls
        for tag in self.tagmap.by_role("spoof_offset"):
            c.offset[tag.node_id] = await self._get(HOLDING_FC, tag)
        for tag in self.tagmap.by_role("spoof_freeze"):
            c.freeze[tag.node_id] = await self._get(HOLDING_FC, tag) != 0.0
        for tag in self.tagmap.by_role("force"):
            c.force[tag.node_id] = await self._get(HOLDING_FC, tag)
        for tag in self.tagmap.by_role("setpoint_delta"):
            c.delta[tag.node_id] = await self._get(HOLDING_FC, tag)

    # ------------------------------------------------------------------ physics tick
    async def tick(self) -> None:
        """Registers -> overlay, one plant step (0.1 s), plant -> registers, truth bookkeeping."""
        await self._read_controls()
        self.plant.step()
        await self._publish()
        self.ticks += 1
        self._record_truth()

    def _in_use(self, role: Role, node: str) -> bool:
        c = self.overlay.controls
        if role == "spoof_offset":
            return abs(c.offset.get(node, 0.0)) > 1e-9
        if role == "spoof_freeze":
            return c.freeze.get(node, False)
        if role == "force":
            return c.force.get(node, -1.0) >= 0.0
        return abs(c.delta.get(node, 0.0)) > 1e-9

    def _record_truth(self) -> None:
        now = self._clock()
        for role in KIND:
            for tag in self.tagmap.by_role(role):  # type: ignore[arg-type]
                key = (tag.role, tag.node_id)
                active = self._in_use(tag.role, tag.node_id)
                if active and key not in self._active:
                    ev = TruthEvent(
                        id=f"evt_{len(self.truth) + 1:03d}",
                        node_id=tag.node_id,
                        tag=tag.tag,
                        role=tag.role,
                        scenario=KIND[tag.role],
                        start_wall=now,
                        start_plant_t=self.plant.t,
                    )
                    self.truth.append(ev)
                    self._active[key] = ev
                elif not active and key in self._active:
                    self._active.pop(key).end_wall = now

    # ------------------------------------------------------------------ real-time loop
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        period = 1.0 / self.hz
        due = loop.time()
        while True:
            self._lag_ms.append(max(0.0, (loop.time() - due) * 1000.0))
            self._tick_wall.append(loop.time())
            await self.tick()
            due += period
            delay = due - loop.time()
            if delay < -5 * period:  # far behind (suspended host): resync instead of bursting
                due = loop.time()
                delay = 0.0
            await asyncio.sleep(max(0.0, delay))

    # ------------------------------------------------------------------ health + truth (HTTP)
    def health(self) -> dict[str, object]:
        lags = sorted(self._lag_ms)
        walls = list(self._tick_wall)
        hz = (len(walls) - 1) / (walls[-1] - walls[0]) if len(walls) > 2 else None
        return {
            "status": "ok",
            "plant_t": round(self.plant.t, 2),
            "ticks": self.ticks,
            "hz_target": self.hz,
            "hz_measured": None if hz is None else round(hz, 2),
            "lag_ms_p95": round(lags[int(0.95 * (len(lags) - 1))], 2) if lags else None,
            "seed": self.seed,
            "registers": {
                "input": self.tagmap.size("input"),
                "holding": self.tagmap.size("holding"),
            },
        }

    async def _handle_http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 2.0)).decode("latin-1").split()
            path = line[1] if len(line) >= 2 and line[0] == "GET" else ""
            body: object | None = None
            if path == "/health":
                body = self.health()
            elif path == "/truth":
                body = [asdict(e) for e in self.truth]
            status = "200 OK" if body is not None else "404 Not Found"
            data = json.dumps(body if body is not None else {"error": "not found"}).encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
                + data
            )
            await writer.drain()
        except (TimeoutError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()


def load(tagmap_path: Path | str, **kw: object) -> PlantEmulator:
    from app.live.tagmap import load_tagmap

    return PlantEmulator(load_tagmap(tagmap_path), **kw)  # type: ignore[arg-type]
