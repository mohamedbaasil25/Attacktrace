"""Tick → detect → localize → emit orchestrator. The only stateful component.

`step_sample()` advances the plant one emit period (5 ticks at 10 Hz = 0.5 s of plant time),
scores the new sample, manages the alert/incident lifecycle and returns the live message.
It is synchronous and clock-injectable; `api/ws.py` drives it from an asyncio task.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from app.attacks import AttackEngine, AttackSpec, GroundTruth
from app.config import Settings
from app.data.simdata import EMIT_EVERY
from app.detect.baseline import BaselineDetector
from app.detect.detector import PERSIST, aggregate
from app.detect.pipeline import Loaded
from app.evidence import classify_transition
from app.localize import Incident as Analysis
from app.localize import Weights, build_incident
from app.localize.incident import FORWARD_S, LOOKBACK_S, SAMPLE_DT
from app.localize.locator import Candidate
from app.schemas import (
    AlertInfo,
    AttackRequest,
    GroundTruthInfo,
    Impact,
    Incident,
    LiveMessage,
    Mode,
    NodeKind,
    NodeState,
    NodeStatus,
    OriginCandidate,
    PathStep,
    Topology,
    TopologyEdge,
    TopologyNode,
    Triple,
)
from app.sim import NODE_IDS, NODES, Plant
from app.storage import IncidentStoreLike

F64 = NDArray[np.float64]

HISTORY = round((LOOKBACK_S + FORWARD_S + 30.0) / SAMPLE_DT)  # samples kept for localization
LOCALIZE_SAMPLES = round(FORWARD_S / SAMPLE_DT) + 1  # incident refines until its window fills
CLOSE_SAMPLES = round(30.0 / SAMPLE_DT)  # quiet time before an incident closes
CONTAINED_SHOW_SAMPLES = round(10.0 / SAMPLE_DT)  # a contained incident stays on screen this long
SUSPECT_FRAC = 0.7  # node score / node threshold that marks a node "suspect"
TOP_ORIGINS = 3
WARMUP_SAMPLES = 40  # 20 s of clean plant scored silently on start and reset


@dataclass
class _Open:
    inc: Incident
    alert_k: int  # absolute sample index of the alert
    alarms: set[str]
    # Nodes whose OWN persistence crossing has been verified to belong to this incident (seeded
    # with the triggering node at creation, grown one hop at a time by `_fold_target`). This is
    # the multi-incident admission "zone" -- deliberately narrower than `inc.path` (the
    # localizer's one-shot window analysis), which can include weakly-correlated downstream nodes
    # that never independently cross their own threshold and would otherwise over-extend the zone.
    member_nodes: set[str] = field(default_factory=set)
    quiet: int = 0
    isolated_t: float | None = None  # plant time of the latest isolate action
    effective: bool = False  # every attack that was live at that moment has been isolated
    calm: int = 0  # consecutive samples with every node score under the alert threshold
    shown: int = 0  # samples a contained incident has stayed on screen


def topology_of(graph: nx.DiGraph) -> Topology:
    """The nodes and the P&ID plus learned edges of the 9-node plant."""
    return Topology(
        nodes=[
            TopologyNode(id=n.id, type=n.type.value, label=n.label, unit=n.unit, lo=n.lo, hi=n.hi)
            for n in NODES
        ],
        edges=[
            TopologyEdge(src=a, dst=b, weight=d["weight"], kind=d["kind"])
            for a, b, d in graph.edges(data=True)
        ],
    )


def origin_candidate(c: Candidate, kind: NodeKind) -> OriginCandidate:
    """Contract entry for a ranked candidate, with its score breakdown."""
    d, o, k = c.contributions()
    w = c.weights
    return OriginCandidate(
        id=c.id,
        type=kind,
        confidence=c.confidence,
        breakdown=Triple(deviation=d, onset=o, causal=k),
        weights=Triple(deviation=w.deviation, onset=w.onset, causal=w.causal),
    )


def is_ambiguous(candidates: list[Candidate], margin: float) -> bool:
    """Top-1 and top-2 confidence closer than `margin`. Read-only: the ranking is not touched."""
    return len(candidates) > 1 and candidates[0].confidence - candidates[1].confidence < margin


def worst_impact(old: Impact | None, new: Impact) -> Impact:
    """Per field, the most severe value seen so far: shortest ETA, highest stress and energy."""
    if old is None:
        return new

    def soonest(a: float | None, b: float | None) -> float | None:
        return b if a is None else a if b is None else min(a, b)

    return Impact(
        t1_overflow_s=soonest(old.t1_overflow_s, new.t1_overflow_s),
        t1_dry_s=soonest(old.t1_dry_s, new.t1_dry_s),
        t2_overflow_s=soonest(old.t2_overflow_s, new.t2_overflow_s),
        t2_dry_s=soonest(old.t2_dry_s, new.t2_dry_s),
        pump_stress={k: max(v, new.pump_stress.get(k, 0.0)) for k, v in old.pump_stress.items()},
        energy_wasted_kwh=max(old.energy_wasted_kwh, new.energy_wasted_kwh),
    )


def _has_hazard(impact: Impact) -> bool:
    """True while any tank has an overflow or dry-run estimate."""
    etas = (impact.t1_overflow_s, impact.t1_dry_s, impact.t2_overflow_s, impact.t2_dry_s)
    return any(e is not None for e in etas)


def _severity_key(inc: Incident) -> tuple[int, float, float]:
    """Sort key for `LiveMessage.incidents` and the frontend triage list (docs/UI_SPEC.md §7):
    Ambiguous incidents pinned near the top, then origin confidence descending, then earliest
    detection first. Ascending sort on this tuple gives that order."""
    confidence = inc.origin[0].confidence if inc.origin else 0.0
    return (0 if inc.ambiguous else 1, -confidence, inc.detected_at)


class Engine:
    mode = "sim"

    def __init__(
        self,
        loaded: Loaded,
        baseline: BaselineDetector,
        graph: nx.DiGraph,
        settings: Settings,
        detector_kind: str | None = None,
        clock: Callable[[], float] = time.time,
        store: IncidentStoreLike | None = None,
    ) -> None:
        self.loaded, self.baseline, self.graph, self.settings = loaded, baseline, graph, settings
        self.detector_kind = detector_kind
        self._clock = clock
        # Undirected, hop-count view of the process graph for the multi-incident fold decision
        # (physical/causal closeness in either direction, not propagation order). The graph is
        # fixed for the engine's lifetime, so this is built once, not per tick.
        self._zone_graph = graph.to_undirected(as_view=True)
        self._weights = Weights(settings.w_deviation, settings.w_onset, settings.w_causal)
        self._contain_samples = max(1, round(settings.contain_s / SAMPLE_DT))
        self._setup_source()
        self._started = clock()
        self.incidents: list[Incident] = []
        self.latest: LiveMessage | None = None
        self.store = store
        self._saved: dict[str, Incident] = {}
        self._init_state()
        self._prewarm()
        # Restart recovery (Phase 3): set *after* prewarming, so the clean warm-up ticks never
        # touch the store, and load *after* prewarm clears `self.incidents` to [] at its own end.
        if store is not None:
            self.incidents = store.load(mode=self.mode)

    # ------------------------------------------------------------------ data source seam
    # SIM reads the simulator; `live.engine.LiveEngine` overrides these to read a protocol source.
    def _setup_source(self) -> None:
        self._attacks = AttackEngine()
        self._plant = Plant(seed=self.settings.seed, overlay=self._attacks)

    def _acquire(self) -> tuple[dict[str, float], dict[str, float]]:
        """One emit period of data: (values as reported to SCADA, physical truth when known)."""
        for _ in range(EMIT_EVERY):
            self._plant.step()
        return self._plant.state(), self._plant.physical_truth()

    def _source_t(self) -> float:
        """Seconds on the source's own clock (plant time in SIM)."""
        return self._plant.t

    # ------------------------------------------------------------------ lifecycle
    def _init_state(self) -> None:
        self.loaded.detector.reset()
        self._hist: deque[tuple[F64, F64, F64]] = deque(maxlen=HISTORY)  # (scores, errors, x)
        self._k = 0
        self._run = 0  # consecutive samples above the global alert threshold (AlertInfo display)
        self._node_run = np.zeros(len(NODE_IDS), dtype=np.int64)  # per-node persistence (admission)
        self._alert_since: float | None = None
        self._open: dict[str, _Open] = {}  # keyed by incident id; multiple can be open at once
        # Monotonic; never derived from len(self.incidents) (that resets on reset()/restart, this
        # must not, or a new incident could collide with -- and `INSERT OR REPLACE` clobber -- an
        # already-persisted row's current-state entry, even though the ledger itself would still
        # hold the original row's real history unmodified under its own event ids).
        self._next_incident_id = self._next_id_from_store()
        self._launched: list[tuple[GroundTruth, float]] = []  # (truth, wall-clock launch time)
        self.incident_impact: dict[str, Impact] = {}  # worst impact seen while each incident ran

    def _next_id_from_store(self) -> int:
        """1 without a store. With one, the next id past every `inc_NNN` this mode has EVER
        persisted -- not just what is currently in `self.incidents` (which `reset()` clears) --
        so a restart or a reset can never reuse an id a prior run already wrote evidence for."""
        if self.store is None:
            return 1
        ids = self.store.load(mode=self.mode)
        max_n = max(
            (int(i.id.removeprefix("inc_")) for i in ids if i.id.startswith("inc_")), default=0
        )
        return max_n + 1

    def reset(self, seed: int | None = None) -> None:
        self._attacks.clear()
        self._plant.reset(self.settings.seed if seed is None else seed)
        self.incidents = []
        self.latest = None
        self._init_state()
        self._prewarm()

    def _prewarm(self) -> None:
        """Bring the detector to steady state before the first message.

        Its first `window` scores are zeros while the window fills, so an attack launched in the
        first seconds lost its onset ordering and was ranked worse (first-place origin in 9 of 15
        rehearsal runs instead of 15 of 15). Scoring 20 s of clean plant up front removes that gap.
        """
        for _ in range(WARMUP_SAMPLES):
            self.step_sample()
        self.incidents, self.latest = [], None

    @property
    def uptime_s(self) -> float:
        return self._clock() - self._started

    def topology(self) -> Topology:
        return topology_of(self.graph)

    # --------------------------------------------------------------------- attacks
    def launch(self, req: AttackRequest) -> str:
        """Schedule an attack starting now. Raises ValueError on an invalid scenario/target."""
        spec = AttackSpec(req.scenario, req.target, self._plant.t, req.duration_s, req.magnitude)
        attack_id = self._attacks.schedule(spec)
        self._launched.append((self._attacks.ground_truth()[-1], self._clock()))
        return attack_id

    def record_external_launch(self, gt: GroundTruth, wall_time: float) -> None:
        """Phase 13: register ground truth for an attack launched outside this engine (the
        attacker tool, against the plant emulator in LIVE mode). Read-only toward the plant:
        this only lets the UI reveal what the attacker did; it never causes anything itself."""
        self._launched.append((gt, wall_time))

    def isolate(
        self, incident_id: str, node_id: str, operator: str | None = None
    ) -> tuple[bool, str | None]:
        """Operator action on the active incident. Returns (applied, reason if refused).

        Applying it only removes an attack's effect where the attack really acts: isolating any
        other node changes nothing. The incident becomes `contained` once an attack that was live
        has been isolated AND every node score then stays under the alert threshold for
        `contain_s`; the simulator knows whether an attack still acts, the detector alone cannot
        see a settled offset. Every outcome -- accepted or refused -- is recorded as an
        `isolation_outcome` ledger event (Phase 3): a rejected attempt is still a security-
        relevant event, and the diff-based `_persist` below would never see it (a refusal never
        changes the incident object at all)."""
        op = self._open.get(incident_id)
        if op is None or op.inc.status not in ("localizing", "open"):
            accepted, reason = False, "Incident is not active"
        elif node_id not in NODE_IDS:
            accepted, reason = False, "Unknown node"
        elif node_id in self._attacks.isolated:
            accepted, reason = False, "Node already isolated"
        else:
            self._attacks.isolate(node_id)
            live = self._attacks.active(self._plant.t)
            op.isolated_t = self._plant.t
            op.effective = bool(live) and all(g.target in self._attacks.isolated for g in live)
            op.calm = 0
            op.inc.isolated_by = operator
            accepted, reason = True, None
        if self.store is not None:
            self.store.ledger.append(
                "isolation_outcome",
                incident_id,
                {"node_id": node_id, "accepted": accepted, "reason": reason, "operator": operator},
            )
        return accepted, reason

    def _truth_for(self, plant_t: float) -> GroundTruthInfo | None:
        """The most recently launched attack genuinely live at `plant_t` -- NOT merely the most
        recently launched one, which could already have ended (a short attack finished minutes
        ago still being "most recent" by launch order, not by relevance). Misattributing ground
        truth to a finished, unrelated attack is worse than reporting none: this field feeds the
        incident's forensic record and the UI's Reveal hit/miss comparison, so a false match reads
        as fabricated evidence."""
        for gt, wall in reversed(self._launched):
            if gt.start_s <= plant_t < gt.end_s:
                return GroundTruthInfo(
                    attack_id=gt.attack_id,
                    scenario=gt.scenario,
                    target=gt.target,
                    started_at=wall,
                    mitre=gt.mitre,
                )
        return None

    # ------------------------------------------------------------------------ tick
    def step_sample(self) -> LiveMessage:
        reported, truth = self._acquire()
        now = self._clock()
        x = np.array([reported[n] for n in NODE_IDS])
        scores = self.loaded.detector.update(x)
        agg = float(aggregate(scores))

        self._run = self._run + 1 if agg > self.loaded.threshold else 0
        alerting = self._run >= PERSIST
        if alerting and self._alert_since is None:
            self._alert_since = now
        elif not alerting:
            self._alert_since = None

        # Per-node persistence, independent of the global aggregate above: the admission signal
        # for multi-incident tracking (which node, if any, just started a sustained deviation),
        # reusing the same per-node thresholds (`loaded.node_thr`) the localizer already trusts.
        node_over = scores > self.loaded.node_thr
        self._node_run = np.where(node_over, self._node_run + 1, 0)
        node_crossed = self._node_run == PERSIST  # True only on the exact crossing sample

        self._hist.append((scores, self.loaded.detector.last_error, x))
        k = self._k
        self._k += 1
        impact = self._impact()
        hazard = impact is not None and _has_hazard(impact)
        self._advance_incident(k, alerting, node_crossed, now, x, scores, hazard=hazard)

        incidents_list = [
            op.inc.model_copy(deep=True)
            for op in sorted(self._open.values(), key=lambda op: _severity_key(op.inc))
        ]
        inc = incidents_list[0] if incidents_list else None
        if inc is not None and impact is not None:
            self.incident_impact[inc.id] = worst_impact(self.incident_impact.get(inc.id), impact)
        msg = LiveMessage(
            t=now,
            mode=cast(Mode, self.mode),
            nodes=self._node_states(reported, truth, scores, inc),
            alert=AlertInfo(since=self._alert_since, score=agg, threshold=self.loaded.threshold)
            if self._alert_since is not None
            else None,
            incident=inc,
            incidents=incidents_list,
            impact=impact,
        )
        self.latest = msg
        return msg

    # ------------------------------------------------------------------- incidents
    def _arrays(self) -> tuple[F64, F64, F64, int]:
        scores = np.array([s for s, _, _ in self._hist])
        errors = np.array([e for _, e, _ in self._hist])
        xs = np.array([v for _, _, v in self._hist])
        return scores, errors, xs, self._k - len(self._hist)  # k of the first stored sample

    def _analyze(self, alert_k: int) -> Analysis:
        scores, errors, xs, k0 = self._arrays()
        return build_incident(
            scores,
            errors,
            xs,
            alert_k - k0,
            self.loaded.detector.norm.mu,
            self.loaded.node_thr,
            self.graph,
            self._weights,
        )

    def _to_schema(
        self, a: Analysis, base: Incident | None, alarms: set[str], new_id: str | None = None
    ) -> Incident:
        return Incident(
            id=base.id if base else cast(str, new_id),
            status=base.status if base else "localizing",
            detected_at=base.detected_at if base else self._clock(),
            origin=[
                origin_candidate(c, cast(NodeKind, c.type)) for c in a.candidates[:TOP_ORIGINS]
            ],
            path=[PathStep(id=n.id, t=n.t, deviation=n.deviation) for n in a.propagation.nodes],
            path_edges=a.propagation.edges,
            explanation=a.explanation.text,
            action=a.explanation.action,
            mitre=a.explanation.mitre,
            mitre_name=a.explanation.mitre_name,
            baseline_alarms=[n for n in NODE_IDS if n in alarms],
            ground_truth=base.ground_truth if base else None,
            mode=cast(Mode, self.mode),
            ambiguous=is_ambiguous(a.candidates, self.settings.gate_margin),
            isolated_by=base.isolated_by if base else None,
        )

    def _fold_target(self, node: str) -> str | None:
        """The id of an already-open incident `node`'s new, sustained deviation belongs to, or
        None to open a fresh one. "Belongs to" means `node` is within `settings.zone_hops`
        undirected graph hops of a node already VERIFIED to belong to that incident
        (`op.member_nodes`): the triggering node at creation, plus every node that has since
        folded in via this same check. This lets a real attack's own multi-hop downstream
        propagation stay one incident even when later hops independently cross their own
        persistence several hops from the origin (each hop only needs to be near an *already
        admitted* member, not near the origin itself) -- while two anchors that were both
        tried (the full localized `path`, and the origin alone) either over- or under-reached:
        `path` includes weakly-correlated nodes the localizer's one-shot window touches without
        them ever independently crossing threshold, over-extending the zone; the origin alone
        can't be reached by a legitimate propagation chain several hops away. Only
        "localizing"/"open" incidents can absorb a new crossing.

        Causality, not just space: an incident whose OWN alert activity has gone quiet for
        `settings.admission_window_s` stops being an admission anchor at all, regardless of how
        spatially close a new crossing is to one of its members. This is deliberately keyed on
        `op.quiet` (already reset to 0 every tick this incident is alerting, by the caller just
        below) rather than a per-member timestamp: a single attack whose downstream effects take
        a while to ripple through the plant stays one incident for as long as it keeps alerting
        continuously, no matter how long ago any individual member first crossed -- only once the
        incident's OWN activity genuinely stops does a later, spatially-nearby crossing stop being
        attributed to it. That is exactly the Phase 16 Scale note's failure mode (one attack's
        propagation reaches most of the plant, goes quiet, and only THEN does a second, unrelated
        attack start nearby) and not the other one a per-member recency check would have broken: a
        single slow attack whose own later hops cross more than one window apart while the
        incident is still actively alerting throughout.

        `admission_window_s` defaults well below `CLOSE_SAMPLES`'s 30 s quiet-close timeout
        (engine.py) on purpose: an incident needs to stop admitting new members meaningfully
        before it closes outright, or this gate would almost never fire before the status check
        above already excludes it."""
        nearby = set(
            nx.single_source_shortest_path_length(
                self._zone_graph, node, cutoff=self.settings.zone_hops
            )
        )
        window_samples = self.settings.admission_window_s / SAMPLE_DT
        for op in self._open.values():
            if op.inc.status not in ("localizing", "open"):
                continue
            if op.quiet > window_samples:
                continue  # this incident's own propagation has gone cold
            if nearby & op.member_nodes:
                return op.inc.id
        return None

    def _advance_incident(
        self,
        k: int,
        alerting: bool,
        node_crossed: NDArray[np.bool_],
        now: float,
        x: F64,
        scores: F64,
        hazard: bool = False,
    ) -> None:
        """`hazard`: the plant still reports an overflow / dry-run estimate. A persistent offset
        stops raising alerts once the plant settles at its new, spoofed equilibrium, so closing on
        a quiet alert alone declared the incident resolved while a tank was still overfilling.

        `node_crossed`: which node(s), if any, had their own persistence counter complete exactly
        this sample (Phase 1 multi-incident admission, SIM/LIVE only). Each crossing is resolved
        independently via `_fold_target`: absorbed into a graph-nearby open incident, or opened as
        a new one -- so a loud, already-open incident does not swallow a quiet, physically distant
        second attack, while a single attack's own downstream propagation still folds into one."""
        new_ids: set[str] = set()
        for i in np.flatnonzero(node_crossed):
            node = NODE_IDS[i]
            target_id = self._fold_target(node)
            if target_id is not None:
                self._open[target_id].member_nodes.add(node)
                continue  # absorbed into an already-open, graph-nearby incident
            _, _, xs, k0 = self._arrays()
            lo = max(0, k - round(LOOKBACK_S / SAMPLE_DT) - k0)
            hits = np.atleast_1d(self.baseline.breaches(xs[lo:]).any(axis=0))
            alarms = {n for n, hit in zip(NODE_IDS, hits.tolist(), strict=True) if hit}
            alarms |= set(self.baseline.alarms(x))  # this sample's own 3-sigma alarms too
            new_id = f"inc_{self._next_incident_id:03d}"
            self._next_incident_id += 1
            inc = self._to_schema(self._analyze(k), None, alarms, new_id=new_id)
            inc.ground_truth = self._truth_for(self._source_t())
            self._open[inc.id] = _Open(inc, k, alarms, member_nodes={node})
            self.incidents.append(inc)
            new_ids.add(inc.id)
            self._persist(inc)

        for inc_id, op in list(self._open.items()):
            if inc_id in new_ids:
                continue  # not advanced on the same tick it was created, same as before
            if op.inc.status == "contained":  # stays visible, then leaves the live feed
                op.shown += 1
                if op.shown >= CONTAINED_SHOW_SAMPLES:
                    del self._open[inc_id]
                self._sync_history(op.inc)
                continue
            op.alarms.update(self.baseline.alarms(x))
            op.quiet = 0 if (alerting or hazard) else op.quiet + 1
            if op.inc.status == "localizing":
                op.inc = self._to_schema(self._analyze(op.alert_k), op.inc, op.alarms)
                if k - op.alert_k + 1 >= LOCALIZE_SAMPLES:
                    op.inc.status = "open"
            else:
                op.inc.baseline_alarms = [n for n in NODE_IDS if n in op.alarms]
            active_status = op.inc.status in ("localizing", "open")
            if op.isolated_t is not None and op.effective and active_status:
                op.calm = op.calm + 1 if float(scores.max()) < self.loaded.threshold else 0
                if op.calm >= self._contain_samples:
                    op.inc.status = "contained"
                    op.inc.contained_at = now
                    op.inc.time_to_contain_s = self._source_t() - op.isolated_t
            if op.inc.status == "open" and op.quiet >= CLOSE_SAMPLES:
                op.inc.status = "closed"
                del self._open[inc_id]
            self._sync_history(op.inc)

    def _sync_history(self, inc: Incident) -> None:
        for i, old in enumerate(self.incidents):
            if old.id == inc.id:
                self.incidents[i] = inc
                break
        self._persist(inc)

    def _persist(self, inc: Incident) -> None:
        """Durable persistence (Phase 3): a no-op without a store (tests, and any mode not wired
        to one). Diffs against the last-saved copy so an unchanged tick never writes -- `save`
        itself decides the ledger event type from that diff via `classify_transition`, same as
        `LiveRuntime._persist` does for LIVE."""
        if self.store is None:
            return
        old = self._saved.get(inc.id)
        if old is not None and old.model_dump_json() == inc.model_dump_json():
            return
        event_type, detail = classify_transition(old, inc)
        self.store.save(inc, event_type=event_type, detail=detail)
        self._saved[inc.id] = inc

    # --------------------------------------------------------------------- message
    def _node_states(
        self,
        reported: dict[str, float],
        truth: dict[str, float],
        scores: F64,
        inc: Incident | None,
    ) -> list[NodeState]:
        live = inc is not None and inc.status not in ("closed", "contained")
        origin = inc.origin[0].id if inc and live else None
        affected = {s.id for s in inc.path} if inc and live else set()
        out = []
        for i, n in enumerate(NODE_IDS):
            status: NodeStatus
            if n == origin:
                status = "origin"
            elif n in affected:
                status = "affected"
            elif scores[i] > SUSPECT_FRAC * self.loaded.node_thr[i]:
                status = "suspect"
            else:
                status = "normal"
            out.append(
                NodeState(
                    id=n,
                    value=reported[n],
                    truth=truth.get(n),
                    score=float(scores[i]),
                    status=status,
                )
            )
        return out

    def _impact(self) -> Impact | None:
        im = self._plant.impact()
        return Impact(
            t1_overflow_s=im.t1_overflow_s,
            t1_dry_s=im.t1_dry_s,
            t2_overflow_s=im.t2_overflow_s,
            t2_dry_s=im.t2_dry_s,
            pump_stress=im.pump_stress,
            energy_wasted_kwh=im.energy_wasted_kwh,
        )
