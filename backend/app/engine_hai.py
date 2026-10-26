"""HAI replay engine: dataset rows -> detect -> localize -> emit, with the same live message as SIM.

The replayer walks one labelled test file at x1-x20 (`AT_HAI_SPEED`), feeding each 1 Hz row to the
streaming detector. Attacks come from the dataset, so there is no attack console in this mode and
no physical ground truth; the incident carries no MITRE tag because HAI does not label one.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray

from app.config import Settings
from app.data.hai import SAMPLE_HZ, HaiFile, process_of
from app.detect.baseline import BaselineDetector
from app.detect.detector import PERSIST, aggregate
from app.detect.hai_pipeline import TOP_K, WINDOW, HaiLoaded
from app.engine import origin_candidate
from app.evidence import classify_transition
from app.localize import Weights
from app.localize.incident import FORWARD_S, LOOKBACK_S
from app.localize.locator import localize
from app.propagate.path import reconstruct
from app.schemas import (
    AlertInfo,
    Incident,
    LiveMessage,
    NodeKind,
    NodeState,
    NodeStatus,
    OriginCandidate,
    PathStep,
    Topology,
    TopologyEdge,
    TopologyNode,
)
from app.storage import IncidentStoreLike

F64 = NDArray[np.float64]

DT = 1.0 / SAMPLE_HZ
LOOKBACK = round(LOOKBACK_S / DT)  # rows before the alert in the incident window
LOCALIZE_ROWS = round(FORWARD_S / DT) + 1  # the incident refines until its window fills
CLOSE_ROWS = 30  # quiet rows before an incident closes
HISTORY = LOOKBACK + LOCALIZE_ROWS + 400  # rows kept (one tick at x20 consumes 10)
SUSPECT_FRAC = 0.7
ADAPT_ROWS = 300  # a node's own recent normal (5 min) sets what counts as unusual for it
ADAPT_FACTOR = 2.0
ADAPT_WARMUP = 120  # rows before the adaptive baseline is trusted
TOP_ORIGINS = 3
START_LEAD_S = 300  # replay starts this long before the first attack
MIN_SPEED, MAX_SPEED = 1.0, 20.0


@dataclass
class _Open:
    inc: Incident
    alert_k: int
    alarms: set[str]
    quiet: int = 0


class HaiEngine:
    mode = "hai"

    def __init__(
        self,
        loaded: HaiLoaded,
        baseline: BaselineDetector,
        replay: HaiFile,
        settings: Settings,
        clock: Callable[[], float] = time.time,
        store: IncidentStoreLike | None = None,
    ) -> None:
        self.loaded, self.baseline, self.replay, self.settings = loaded, baseline, replay, settings
        self.graph = loaded.graph
        self.detector_kind: str | None = loaded.kind
        self.speed = min(MAX_SPEED, max(MIN_SPEED, settings.hai_speed))
        self._clock = clock
        self._started = clock()
        self._weights = Weights(settings.w_deviation, settings.w_onset, settings.w_causal)
        windows = replay.windows()
        self._start = max(0, (windows[0][0] if windows else 0) - round(START_LEAD_S * SAMPLE_HZ))
        self.incidents: list[Incident] = []
        self.latest: LiveMessage | None = None
        self.store = store
        self._saved: dict[str, Incident] = {}
        self._init_state()
        if store is not None:  # restart recovery (Phase 3), same convention as SIM/LIVE
            self.incidents = store.load(mode=self.mode)

    def _next_id_from_store(self) -> int:
        """See `Engine._next_id_from_store`: never derived from `len(self.incidents)` alone,
        which `reset()` clears -- that would let a post-reset incident collide with, and
        `INSERT OR REPLACE` clobber, an already-persisted row's current-state entry."""
        if self.store is None:
            return len(self.incidents) + 1
        ids = self.store.load(mode=self.mode)
        max_n = max(
            (int(i.id.removeprefix("inc_")) for i in ids if i.id.startswith("inc_")), default=0
        )
        return max(max_n + 1, len(self.incidents) + 1)

    # ------------------------------------------------------------------ lifecycle
    def _init_state(self) -> None:
        self.loaded.detector.reset()
        self._pos = self._start  # next row of the replay file to consume
        self._carry = 0.0  # fractional rows owed by the replay speed
        self._hist: deque[tuple[F64, F64, F64]] = deque(maxlen=HISTORY)  # (scores, errors, row)
        self._k = 0
        self._run = 0
        self._alert_since: float | None = None
        self._open: _Open | None = None
        self._scores = np.zeros(len(self.loaded.features))
        self._slow = np.zeros(len(self.loaded.features))  # slow per-node score baseline
        self._row = self.replay.x[self._pos]

    def reset(self) -> None:
        self.incidents = []
        self.latest = None
        self._init_state()

    @property
    def uptime_s(self) -> float:
        return self._clock() - self._started

    def topology(self) -> Topology:
        lo, hi = self.replay.x.min(axis=0), self.replay.x.max(axis=0)
        names = self.loaded.features
        return Topology(
            nodes=[
                TopologyNode(
                    id=n,
                    type=t,
                    label=n,
                    unit="",
                    lo=float(lo[i]),
                    hi=float(hi[i]),
                )
                for i, (n, t) in enumerate(zip(names, self.loaded.types, strict=True))
            ],
            edges=[
                TopologyEdge(src=a, dst=b, weight=d["weight"], kind=d["kind"])
                for a, b, d in self.graph.edges(data=True)
            ],
        )

    # ------------------------------------------------------------------------ tick
    def _consume(self, row: F64) -> bool:
        """Score one dataset row; returns whether the alert is currently on."""
        scores = self.loaded.detector.update(row)
        self._scores, self._row = scores, row
        first = self._k == WINDOW  # the first row with a full window gives the first real score
        self._slow = scores.copy() if first else self._slow + (scores - self._slow) / ADAPT_ROWS
        self._hist.append((scores, self.loaded.detector.last_error, row))
        self._k += 1
        self._run = self._run + 1 if float(aggregate(scores, TOP_K)) > self.loaded.threshold else 0
        return self._run >= PERSIST

    def step_sample(self) -> LiveMessage:
        self._carry += self.speed * self.settings.ws_period_s * SAMPLE_HZ
        rows = int(self._carry)
        self._carry -= rows
        alerting = self._run >= PERSIST
        for _ in range(rows):
            alerting = self._consume(self.replay.x[self._pos])
            self._pos = self._start if self._pos + 1 >= len(self.replay.x) else self._pos + 1
            if alerting and self._open is None:
                self._open_incident()  # opens at the first alerting row, as in SIM
        now = self._clock()
        if alerting and self._alert_since is None:
            self._alert_since = now
        elif not alerting:
            self._alert_since = None
        self._advance_incident(alerting, rows)
        agg = float(aggregate(self._scores, TOP_K))
        inc = self._open.inc if self._open else None
        msg = LiveMessage(
            t=now,
            mode="hai",
            nodes=self._node_states(inc),
            alert=AlertInfo(since=self._alert_since, score=agg, threshold=self.loaded.threshold)
            if self._alert_since is not None
            else None,
            incident=inc.model_copy(deep=True) if inc else None,
            # HAI stays single-incident; no fold/multi logic, just the additive back-compat shape.
            incidents=[inc.model_copy(deep=True)] if inc else [],
            impact=None,
        )
        self.latest = msg
        return msg

    # ------------------------------------------------------------------- incidents
    def _analysis(
        self, alert_k: int
    ) -> tuple[list[OriginCandidate], list[PathStep], list[tuple[str, str]], str, str]:
        names = self.loaded.features
        scores = np.array([s for s, _, _ in self._hist])
        errors = np.array([e for _, e, _ in self._hist])
        rows = np.array([r for _, _, r in self._hist])
        a = alert_k - (self._k - len(self._hist))
        lo, hi = max(0, a - LOOKBACK), min(len(scores), a + LOCALIZE_ROWS)
        cands = localize(
            scores[lo:hi],
            self.loaded.node_thr,
            self.graph,
            self._weights,
            names=names,
            errors=errors[lo:hi],
            types=self.loaded.types,
        )
        by_idx = {n: i for i, n in enumerate(names)}
        cross = np.full(len(names), -1, dtype=np.int64)
        dev = np.zeros(len(names))
        for c in cands:
            cross[by_idx[c.id]] = -1 if c.onset_idx is None else c.onset_idx
            dev[by_idx[c.id]] = c.deviation
        prop = reconstruct(self.graph, cross, dev, DT, names=names, origin=cands[0].id)
        top = cands[0]
        k = by_idx[top.id]
        mu = self.loaded.detector.norm.mu[k]
        direction = "high" if float(rows[max(lo, hi - 10) : hi, k].mean()) > mu else "low"
        later = [n.id for n in prop.nodes if n.id != top.id][:2]
        proc = process_of(top.id)
        text = f"Origin {top.id} ({top.type}, {proc}) · reads {direction}" + "".join(
            f" → {n}" for n in later
        )
        origin = [origin_candidate(c, cast(NodeKind, c.type)) for c in cands[:TOP_ORIGINS]]
        path = [PathStep(id=n.id, t=n.t, deviation=n.deviation) for n in prop.nodes]
        return origin, path, prop.edges, text, f"Inspect {proc} · check {top.id}"

    def _make(self, alert_k: int, base: Incident | None, alarms: set[str]) -> Incident:
        origin, path, edges, text, action = self._analysis(alert_k)
        return Incident(
            mode="hai",
            id=base.id if base else f"inc_{self._next_id_from_store():03d}",
            status=base.status if base else "localizing",
            detected_at=base.detected_at if base else self._clock(),
            origin=origin,
            path=path,
            path_edges=edges,
            explanation=text,
            action=action,
            mitre="",  # HAI carries no ATT&CK labels; the UI hides empty tags
            mitre_name="",
            baseline_alarms=[n for n in self.loaded.features if n in alarms],
            ground_truth=None,
        )

    def _open_incident(self) -> None:
        k = self._k - 1
        arr = np.array([r for _, _, r in self._hist])
        lo = max(0, len(arr) - 1 - LOOKBACK)
        hits = np.atleast_1d(self.baseline.breaches(arr[lo:]).any(axis=0))
        alarms = {n for n, h in zip(self.loaded.features, hits.tolist(), strict=True) if h}
        inc = self._make(k, None, alarms)
        self._open = _Open(inc, k, alarms)
        self.incidents.append(inc)
        self._persist(inc)

    def _advance_incident(self, alerting: bool, rows: int) -> None:
        op = self._open
        if op is None or rows == 0:
            return
        op.alarms.update(self.baseline.alarms(self._row))
        op.quiet = 0 if alerting else op.quiet + rows
        if op.inc.status == "localizing":
            op.inc = self._make(op.alert_k, op.inc, op.alarms)
            if self._k - op.alert_k >= LOCALIZE_ROWS:
                op.inc.status = "open"
        else:
            op.inc.baseline_alarms = [n for n in self.loaded.features if n in op.alarms]
        if op.inc.status == "open" and op.quiet >= CLOSE_ROWS:
            op.inc.status = "closed"
            self._open = None
        for i, old in enumerate(self.incidents):
            if old.id == op.inc.id:
                self.incidents[i] = op.inc
        self._persist(op.inc)

    def _persist(self, inc: Incident) -> None:
        """Durable persistence (Phase 3): a no-op without a store. See `Engine._persist` -- same
        diff-then-classify shape, duplicated rather than shared because `HaiEngine` does not
        inherit from `Engine` (a separate, simpler single-incident lifecycle; see module
        docstring)."""
        if self.store is None:
            return
        old = self._saved.get(inc.id)
        if old is not None and old.model_dump_json() == inc.model_dump_json():
            return
        event_type, detail = classify_transition(old, inc)
        self.store.save(inc, event_type=event_type, detail=detail)
        self._saved[inc.id] = inc

    # --------------------------------------------------------------------- message
    def _unusual(self, i: int, thr: float) -> bool:
        """Suspect = high against its clean threshold AND clearly above the node's own recent
        behaviour. Test days run hotter than the training data, so the threshold alone would flag
        half the plant all the time."""
        if self._scores[i] <= SUSPECT_FRAC * thr:
            return False
        return self._k > ADAPT_WARMUP and self._scores[i] > ADAPT_FACTOR * self._slow[i]

    def _node_states(self, inc: Incident | None) -> list[NodeState]:
        names, thr = self.loaded.features, self.loaded.node_thr
        live = inc is not None and inc.status != "closed"
        origin = inc.origin[0].id if live and inc and inc.origin else None
        affected = {s.id for s in inc.path} if live and inc else set()
        out: list[NodeState] = []
        for i, n in enumerate(names):
            status: NodeStatus
            if n == origin:
                status = "origin"
            elif n in affected:
                status = "affected"
            elif self._unusual(i, thr[i]):
                status = "suspect"
            else:
                status = "normal"
            out.append(
                NodeState(
                    id=n,
                    value=float(self._row[i]),
                    truth=None,
                    score=float(self._scores[i]),
                    status=status,
                )
            )
        return out
