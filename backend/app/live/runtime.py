"""LiveRuntime: what the API and the WebSocket loop talk to when the mode is LIVE.

It wraps the `LiveEngine` (detection, localization, incidents) with what a live source needs around
it: a `waiting` phase until every node has been read once, a `calibrating` phase while a clean
recording is made and the detector trained (when no LIVE model exists), and SQLite persistence of
incidents. It never writes to the plant.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable

import networkx as nx

from app.config import Settings
from app.detect.pipeline import load_baseline, load_detector
from app.engine import topology_of
from app.graph import load_graph, merge_graph
from app.live.config import LiveConfig, LiveConfigError, load_live
from app.live.engine import LIVE_READ_ONLY, LiveEngine
from app.live.quality import excluded_from_ranking
from app.live.source import LiveSource, Snapshot, SourceNotReadyError
from app.live.store import IncidentStore
from app.live.tagmap import TagMap
from app.live.train import SAMPLE_S, LiveRecorder, live_dir, live_models_ready, train_live
from app.schemas import (
    Incident,
    LiveMessage,
    NodeState,
    SourceInfo,
    SourceState,
    TagHealth,
    Topology,
)
from app.sim import NODE_IDS

log = logging.getLogger("attacktrace.live")

Phase = str  # "waiting" | "calibrating" | "running"


class LiveRuntime:
    mode = "live"

    def __init__(
        self,
        settings: Settings,
        cfg: LiveConfig,
        tagmap: TagMap,
        source: LiveSource | None = None,
        store: IncidentStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self.settings, self.cfg, self.tagmap = settings, cfg, tagmap
        self.source = source or LiveSource(cfg, tagmap)
        self.store = store
        self.latest: LiveMessage | None = None
        self.detector_kind: str | None = None
        self.engine: LiveEngine | None = None
        self.train_error: str | None = None
        self._started = time.time()
        self._history: list[Incident] = store.load() if store else []
        self._saved: dict[str, str] = {}
        self._training: asyncio.Task[None] | None = None
        self.recorder = LiveRecorder(self._target_samples())
        self._graph = self._load_graph()
        self.try_load_engine()

    # ------------------------------------------------------------------ setup
    def _target_samples(self) -> int:
        return round(self.settings.live_train_min * 60 / SAMPLE_S)

    def _load_graph(self) -> nx.DiGraph:
        for d in (live_dir(self.settings.models_dir), self.settings.models_dir):
            if (d / "graph.json").exists():
                return load_graph(d / "graph.json")
        return merge_graph([])  # the static P&ID only

    def try_load_engine(self) -> bool:
        """Start running when a LIVE model exists."""
        d = live_dir(self.settings.models_dir)
        if self.engine is not None or not live_models_ready(self.settings.models_dir):
            return self.engine is not None
        loaded = load_detector(d)
        meta = json.loads((d / "detector.json").read_text())
        self.detector_kind = str(meta["active"])
        self._graph = load_graph(d / "graph.json")
        self.engine = LiveEngine(
            loaded,
            load_baseline(d),
            self._graph,
            self.settings,
            self.source,
            detector_kind=self.detector_kind,
            clock=self._clock,
        )
        self.engine.incidents = list(self._history)  # ids continue after a restart
        max_n = max(
            (int(i.id.removeprefix("inc_")) for i in self._history if i.id.startswith("inc_")),
            default=0,
        )
        self.engine._next_incident_id = max_n + 1  # avoid colliding with restored history ids
        return True

    # ------------------------------------------------------------------ views
    @property
    def incidents(self) -> list[Incident]:
        return self.engine.incidents if self.engine is not None else self._history

    @property
    def uptime_s(self) -> float:
        return time.time() - self._started

    @property
    def phase(self) -> Phase:
        if self.engine is not None:
            return "running"
        return "calibrating" if self.source.ready else "waiting"

    def topology(self) -> Topology:
        return topology_of(self._graph)

    def available(self) -> tuple[bool, str | None]:
        """Whether LIVE can be switched on right now, and if not, why."""
        st = self.source.status()
        if st.connected:
            return True, None
        return False, st.reason or "waiting for the plant source"

    def source_info(self) -> SourceInfo:
        st = self.source.status()
        state: SourceState = st.state  # type: ignore[assignment]
        progress: float | None = None
        reason = st.reason
        if self.engine is None and self.source.ready and state == "connected":
            state, progress = "calibrating", self.recorder.progress
            reason = self.train_error or reason
        faults = self._faults()
        if faults and reason is None:
            reason = "source-fault: " + ", ".join(faults[:3])
        return SourceInfo(
            mode="live",
            connected=st.connected,
            protocol=st.protocol,
            state=state,
            latency_ms_p50=st.latency_ms_p50,
            latency_ms_p95=st.latency_ms_p95,
            samples_per_s=st.samples_per_s,
            dropped=st.dropped,
            reason=reason,
            progress=progress,
        )

    def _faults(self) -> list[str]:
        if not self.source.ready:
            return []
        snap = self.source.snapshot()
        return [f"{n} {q}" for n, q in snap.quality.items() if excluded_from_ranking(q)]

    def health(self) -> list[TagHealth]:
        return [
            TagHealth(
                tag=h.tag,
                node_id=h.node_id,
                quality=h.quality,
                age_ms=h.age_ms,
                last_value=h.last_value,
            )
            for h in self.source.health()
        ]

    # ------------------------------------------------------------------ tick
    def step_sample(self) -> LiveMessage:
        if self.engine is not None:
            try:
                msg = self.engine.step_sample()
            except SourceNotReadyError:
                return self._plain(self.source.snapshot())
            self._persist()
            self.latest = msg
            return msg
        snap = self.source.snapshot()
        if snap.ready:
            self.recorder.add(snap)
            if self.recorder.done and self._training is None:
                self._training = asyncio.get_running_loop().create_task(self._train())
        self.latest = self._plain(snap)
        return self.latest

    def _plain(self, snap: Snapshot) -> LiveMessage:
        """A message with data but no detection (waiting or calibrating): no alert, no incident."""
        msg = LiveMessage(
            t=self._clock(),
            mode="live",
            nodes=[
                NodeState(
                    id=n,
                    value=snap.values[n],
                    truth=None,
                    score=0.0,
                    status="normal",
                    quality=snap.quality[n],
                )
                for n in NODE_IDS
            ],
            alert=None,
            incident=None,
            impact=None,
            source_latency_ms=None
            if snap.source_latency_ms == float("inf")
            else snap.source_latency_ms,
        )
        self.latest = msg
        return msg

    async def _train(self) -> None:
        try:
            x = self.recorder.array()
            await asyncio.to_thread(train_live, x, self.settings.models_dir, None, 40, False)
            self.try_load_engine()
            self.train_error = None
            log.info("LIVE detector trained on %d clean samples", len(x))
        except Exception as exc:
            self.train_error = f"calibration failed: {exc}"
            log.exception("LIVE calibration failed")
            self.recorder = LiveRecorder(self._target_samples())  # try again from scratch
        finally:
            self._training = None

    def _persist(self) -> None:
        if self.store is None or self.engine is None:
            return
        for inc in self.engine.incidents[-5:]:  # only recent incidents can still change
            body = inc.model_dump_json()
            if self._saved.get(inc.id) != body:
                self.store.save(inc)
                self._saved[inc.id] = body

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        """Clear the live view and start over. Stored incidents stay in the database."""
        if self.engine is not None:
            self.engine.reset()
        else:
            self.recorder = LiveRecorder(self._target_samples())
            self.source.reset()
        self._history = []
        self.latest = None

    def clock_now(self) -> float:
        """Public accessor for the launcher in `app.api.live_attack` (kept out of `app/live`, the
        read-only ingestion package) to timestamp ground truth on the same clock as this runtime."""
        return self._clock()

    # ------------------------------------------------------------------ read-only toward the plant
    def isolate(
        self, incident_id: str, node_id: str, operator: str | None = None
    ) -> tuple[bool, str | None]:
        return False, LIVE_READ_ONLY

    async def stop(self) -> None:
        if self._training is not None:
            self._training.cancel()
        await self.source.stop()
        if self.store is not None:
            self.store.close()


def build_live_runtime(settings: Settings) -> tuple[LiveRuntime | None, str | None]:
    """The LIVE runtime, or (None, reason). A bad LIVE setting never stops SIM or HAI."""
    try:
        cfg, tagmap = load_live(settings)
        store = IncidentStore(settings.live_db)
        return LiveRuntime(settings, cfg, tagmap, store=store), None
    except LiveConfigError as exc:
        log.error("LIVE disabled: %s", exc)
        return None, str(exc)
    except Exception as exc:
        log.exception("LIVE disabled")
        return None, f"LIVE could not start: {exc}"
