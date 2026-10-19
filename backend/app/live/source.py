"""LiveSource: what the engine reads in LIVE mode, in place of the simulator's `Plant`.

It owns the poller, the aligner and the quality tracker. `snapshot()` returns every node's value
as of the engine tick (last value held up to `max_age_s`), its quality and age; `health()` and
`status()` feed the API. Nothing here writes to the plant.
"""

import asyncio
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.live.align import Aligner
from app.live.config import LiveConfig
from app.live.modbus import ModbusPoller, ReadOnlyClient
from app.live.quality import Quality, QualityTracker, TagSpec
from app.live.tagmap import TagMap
from app.sim.topology import SENSORS

RATE_WINDOW_S = 10.0


class SourceNotReadyError(RuntimeError):
    """No usable first reading for every node yet."""


@dataclass(frozen=True)
class Snapshot:
    values: dict[str, float]  # node_id -> value, held from the last sample
    quality: dict[str, Quality]
    age_ms: dict[str, float]
    source_latency_ms: float  # age of the newest sample at this moment
    ready: bool  # every node has been read at least once


@dataclass(frozen=True)
class TagHealth:
    tag: str
    node_id: str
    quality: Quality
    age_ms: float | None
    last_value: float | None


@dataclass(frozen=True)
class SourceStatus:
    mode: str
    connected: bool
    protocol: str
    state: str  # connected | stale | connecting | down
    latency_ms_p50: float | None
    latency_ms_p95: float | None
    samples_per_s: float
    dropped: int
    reason: str | None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


class LiveSource:
    def __init__(
        self,
        cfg: LiveConfig,
        tagmap: TagMap,
        clock: Callable[[], float] = time.time,
        client_factory: Callable[[], ReadOnlyClient] | None = None,
    ) -> None:
        self.cfg, self.tagmap, self._clock = cfg, tagmap, clock
        self._value_tags = tagmap.by_role("value")
        names = [t.tag for t in self._value_tags]
        self.aligner = Aligner(names, cfg.max_age_s)
        self.tracker = QualityTracker(
            {t.tag: TagSpec(t.min, t.max, sensor=t.node_id in SENSORS) for t in self._value_tags},
            cfg.stale_after_s,
            cfg.max_age_s,
            cfg.frozen_after_s,
        )
        self.poller = ModbusPoller(cfg, tagmap, self._on_sample, client_factory, clock)
        self._task: asyncio.Task[None] | None = None
        self._rate: deque[float] = deque(maxlen=20000)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.poller.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait({self._task}, timeout=3.0)  # bounded: never hang on shutdown
            self._task = None
        await self.poller.stop()

    def reset(self) -> None:
        """Forget what was read (a fresh start of the engine); the connection stays up."""
        self.aligner.clear()
        self.tracker.reset()
        self._rate.clear()

    # ------------------------------------------------------------------ data
    def _on_sample(self, tag: str, value: float, ts: float) -> None:
        if self.aligner.add(tag, value, ts):
            self.tracker.observe(tag, value, ts)
            self._rate.append(ts)

    def snapshot(self, now: float | None = None) -> Snapshot:
        now = self._clock() if now is None else now
        values: dict[str, float] = {}
        quality: dict[str, Quality] = {}
        age: dict[str, float] = {}
        ready = True
        newest = 0.0
        for t in self._value_tags:
            last = self.aligner.last(t.tag)
            held = self.aligner.at(t.tag, now) or last
            if held is None:
                ready = False
                values[t.node_id] = (t.min + t.max) / 2.0
                age[t.node_id] = float("inf")
            else:
                values[t.node_id] = held.value
                age[t.node_id] = max(0.0, (now - held.ts) * 1000.0)
                newest = max(newest, held.ts)
            quality[t.node_id] = self.tracker.classify(t.tag, now)
        latency = max(0.0, (now - newest) * 1000.0) if newest else float("inf")
        return Snapshot(values, quality, age, latency, ready)

    @property
    def ready(self) -> bool:
        return all(self.aligner.last(t.tag) is not None for t in self._value_tags)

    # ------------------------------------------------------------------ views for the API
    def health(self, now: float | None = None) -> list[TagHealth]:
        now = self._clock() if now is None else now
        out = []
        for t in self._value_tags:
            last = self.aligner.last(t.tag)
            out.append(
                TagHealth(
                    tag=t.tag,
                    node_id=t.node_id,
                    quality=self.tracker.classify(t.tag, now),
                    age_ms=None if last is None else max(0.0, (now - last.ts) * 1000.0),
                    last_value=None if last is None else last.value,
                )
            )
        return out

    def status(self, now: float | None = None) -> SourceStatus:
        now = self._clock() if now is None else now
        p = self.poller
        connected = p.state == "connected"
        newest = max(
            (s.ts for t in self._value_tags if (s := self.aligner.last(t.tag)) is not None),
            default=None,
        )
        stale = connected and newest is not None and now - newest > self.cfg.stale_after_s
        state = "stale" if stale else p.state
        reason: str | None = None
        if p.state == "down":
            reason = p.last_error or "source unreachable"
        elif stale and newest is not None:
            reason = f"no data for {now - newest:.1f} s"
        recent = sum(1 for ts in self._rate if now - ts <= RATE_WINDOW_S)
        lat = list(p.latency_ms)
        return SourceStatus(
            mode="live",
            connected=connected and not stale,
            protocol="modbus",
            state=state,
            latency_ms_p50=statistics.median(lat) if lat else None,
            latency_ms_p95=_pct(lat, 0.95),
            samples_per_s=recent / RATE_WINDOW_S,
            dropped=self.aligner.dropped_out_of_order,
            reason=reason,
        )
