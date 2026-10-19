"""LiveEngine: the SIM engine fed by a protocol source instead of the simulator.

Detection, localization, propagation and explanation are the inherited `Engine` code, unchanged.
Only the data source differs (`_acquire`), plus the things a live plant cannot provide: no physical
truth, no impact model, no attack launcher of its own and no isolate (read-only toward the plant).

Quality-aware scoring: a tag whose data is `stale`, `missing` or `out_of_range` is a data fault, not
an attack. Its value is replaced, for the detector only, by the model's own expectation, so it adds
no forecast error and cannot rank as an origin. `frozen` is advisory and is never masked: a frozen
sensor is exactly what a freeze attack looks like.
"""

import time
from collections.abc import Callable

import networkx as nx

from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.live.quality import excluded_from_ranking
from app.live.source import LiveSource, Snapshot, SourceNotReadyError
from app.schemas import AttackRequest, Impact, LiveMessage
from app.sim import NODE_IDS

LIVE_READ_ONLY = "live-read-only"


class LiveEngine(Engine):
    mode = "live"

    def __init__(
        self,
        loaded: Loaded,
        baseline: BaselineDetector,
        graph: nx.DiGraph,
        settings: Settings,
        source: LiveSource,
        detector_kind: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.source = source
        self.last_snapshot: Snapshot | None = None
        self.masked: list[str] = []  # nodes neutralised on the last tick (data faults)
        super().__init__(loaded, baseline, graph, settings, detector_kind, clock)

    # -- the seam -----------------------------------------------------------------------
    def _setup_source(self) -> None:
        return None  # the LiveSource is created and started by the app

    def _prewarm(self) -> None:
        return None  # the detector warms up on the live stream

    def _acquire(self) -> tuple[dict[str, float], dict[str, float]]:
        snap = self.source.snapshot(self._clock())
        if not snap.ready:
            raise SourceNotReadyError("waiting for the first reading of every node")
        self.last_snapshot = snap
        values = dict(snap.values)
        self.masked = []
        if not self.settings.live_include_bad_quality:
            self.masked = [n for n in NODE_IDS if excluded_from_ranking(snap.quality[n])]
            expected = self.loaded.detector.predict_next() if self.masked else None
            if expected is not None:  # until the window is full the detector reports no error
                for n in self.masked:
                    values[n] = float(expected[NODE_IDS.index(n)])
        return values, {}  # a live plant has no physical truth to show

    def _source_t(self) -> float:
        return self._clock() - self._started

    def _impact(self) -> Impact | None:
        return None

    def step_sample(self) -> LiveMessage:
        msg = super().step_sample()
        snap = self.last_snapshot
        if snap is not None:
            for node in msg.nodes:
                node.value = snap.values[node.id]  # show what was read, not the stand-in
                node.quality = snap.quality[node.id]
            if snap.source_latency_ms != float("inf"):
                msg.source_latency_ms = snap.source_latency_ms
        return msg

    # -- lifecycle ------------------------------------------------------------------------
    def reset(self, seed: int | None = None) -> None:
        self.incidents = []
        self.latest = None
        self.source.reset()
        self._init_state()

    # -- read-only toward the plant -------------------------------------------------------
    def launch(self, req: AttackRequest) -> str:
        raise ValueError("LIVE attacks go through the attacker tool")

    def isolate(
        self, incident_id: str, node_id: str, operator: str | None = None
    ) -> tuple[bool, str | None]:
        return False, LIVE_READ_ONLY
