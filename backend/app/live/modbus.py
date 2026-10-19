"""Async Modbus TCP poller. READ-ONLY toward the plant.

`ReadOnlyModbus` is the only Modbus object AttackTrace's ingestion owns. It can connect, read
input registers and close; it has no write method and does not expose the client behind it.
The poller batches reads by contiguous register block, bounds requests in flight, times every
request out, and reconnects with exponential backoff and jitter.
"""

import asyncio
import contextlib
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeVar

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from app.live.config import LiveConfig
from app.live.tagmap import Tag, TagMap, decode

T = TypeVar("T")
Sink = Callable[[str, float, float], None]  # (tag, engineering value, receive time)
State = Literal["connecting", "connected", "down"]


class ReadError(Exception):
    """A request failed (timeout, protocol error or lost connection)."""


async def bounded(aw: Awaitable[T], timeout: float) -> T:
    """Await `aw` for at most `timeout` seconds. Unlike `asyncio.wait_for` this never waits for the
    inner task to finish after a timeout or cancel: pymodbus can swallow a cancellation inside
    `connect()`, and the poller must still be stoppable."""
    task = asyncio.ensure_future(aw)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        raise TimeoutError(f"no answer within {timeout:g} s")
    return task.result()


class ReadOnlyClient(Protocol):
    @property
    def connected(self) -> bool: ...
    async def connect(self) -> bool: ...
    async def read_input_registers(self, address: int, count: int) -> list[int]: ...
    async def close(self) -> None: ...


class ReadOnlyModbus:
    """Connect, read input registers, close. Nothing else is reachable from here."""

    __slots__ = ("_c", "_device", "_timeout")

    def __init__(self, host: str, port: int, timeout_s: float, device_id: int) -> None:
        self._c = AsyncModbusTcpClient(
            host, port=port, timeout=timeout_s, retries=0, reconnect_delay=0
        )  # reconnect_delay=0: the poller owns reconnecting
        self._device, self._timeout = device_id, timeout_s

    @property
    def connected(self) -> bool:
        return bool(self._c.connected)

    async def connect(self) -> bool:
        try:
            await bounded(self._c.connect(), self._timeout)
        except (OSError, TimeoutError, ModbusException):
            return False
        return self.connected

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        try:
            rr = await bounded(
                self._c.read_input_registers(address, count=count, device_id=self._device),
                self._timeout + 0.5,
            )
        except (OSError, TimeoutError, ModbusException) as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
        if rr.isError():
            raise ReadError(str(rr))
        return [int(r) for r in rr.registers]

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            self._c.close()


class ModbusPoller:
    def __init__(
        self,
        cfg: LiveConfig,
        tagmap: TagMap,
        sink: Sink,
        client_factory: Callable[[], ReadOnlyClient] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.cfg, self.tagmap, self._sink = cfg, tagmap, sink
        self._factory = client_factory or (
            lambda: ReadOnlyModbus(cfg.host, cfg.port, cfg.timeout_s, tagmap.device_id)
        )
        self._clock, self._sleep, self._rng = clock, sleep, rng or random.Random(0)
        self._blocks = list(tagmap.blocks("input", max_gap=cfg.block_gap))
        self._tags: dict[tuple[int, int], list[Tag]] = {
            (start, count): [
                t
                for t in tagmap.by_role("value")
                if start <= t.address and t.address + t.width <= start + count
            ]
            for start, count in self._blocks
        }
        self._inflight = asyncio.Semaphore(cfg.max_in_flight)
        self._client: ReadOnlyClient | None = None
        self.state: State = "connecting"
        self.last_error: str | None = None
        self.latency_ms: deque[float] = deque(maxlen=400)
        self.sample_ts: deque[float] = deque(maxlen=4000)
        self.reads_ok = 0
        self.reads_failed = 0
        self.reconnects = 0
        self.backoffs: list[float] = []  # delays slept between connection attempts (for tests)

    # ------------------------------------------------------------------ backoff
    def backoff(self, attempt: int) -> float:
        """Exponential delay with +-20% jitter, capped at backoff_max_s."""
        base = min(self.cfg.backoff_max_s, self.cfg.backoff_base_s * 2**attempt)
        return float(base * (1.0 + 0.2 * (2.0 * self._rng.random() - 1.0)))

    # ------------------------------------------------------------------ reads
    async def _read_block(self, client: ReadOnlyClient, block: tuple[int, int]) -> bool:
        start, count = block
        async with self._inflight:
            t0 = time.perf_counter()
            try:
                regs = await client.read_input_registers(start, count)
            except ReadError as exc:
                self.reads_failed += 1
                self.last_error = str(exc)
                return False
        self.latency_ms.append((time.perf_counter() - t0) * 1000.0)
        now = self._clock()
        for tag in self._tags[block]:
            i = tag.address - start
            self._sink(tag.tag, decode(tag, regs[i : i + tag.width]), now)
            self.sample_ts.append(now)
        self.reads_ok += 1
        return True

    async def poll_once(self, client: ReadOnlyClient) -> int:
        """Read every block concurrently (bounded); returns how many blocks succeeded."""
        results = await asyncio.gather(*(self._read_block(client, b) for b in self._blocks))
        return sum(results)

    # ------------------------------------------------------------------ loop
    async def run(self) -> None:
        attempt = 0
        failed_cycles = 0
        while True:
            client = self._client
            if client is not None and not client.connected:  # the link dropped under us
                self.state = "down"
                self.last_error = self.last_error or "connection lost"
                await client.close()
                self._client = client = None
            if client is None or not client.connected:
                if self.state != "down":  # after a failure stay `down` until the link is back
                    self.state = "connecting"
                client = self._factory()
                if not await client.connect():
                    self.state = "down"
                    self.last_error = self.last_error or "connection refused"
                    await client.close()
                    delay = self.backoff(attempt)
                    attempt += 1
                    self.backoffs.append(delay)
                    await self._sleep(delay)
                    continue
                self._client, attempt, failed_cycles = client, 0, 0
                self.reconnects += 1
                self.state = "connected"
                self.last_error = None
            started = time.perf_counter()
            ok = await self.poll_once(client)
            if ok == 0:  # nothing answered: drop the connection and start over with backoff
                failed_cycles += 1
                if failed_cycles >= 2 or not client.connected:
                    await client.close()
                    self._client, self.state = None, "down"
                    delay = self.backoff(attempt)
                    attempt += 1
                    self.backoffs.append(delay)
                    await self._sleep(delay)
                    continue
            else:
                failed_cycles = 0
            await self._sleep(max(0.0, self.cfg.poll_s - (time.perf_counter() - started)))

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
