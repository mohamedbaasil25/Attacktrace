"""Pydantic models: single source of truth for the REST + WebSocket contract (§5.9).

FROZEN after Phase 4 — mirrored by frontend/src/lib/types.ts. Changing a field name, type or
meaning needs explicit approval. `incidents` (Phase 15+) is an additive exception: `incident`
is unchanged in shape but is now derived from `incidents` (most severe, or None).
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.attacks import Scenario

Quality = Literal["good", "stale", "missing", "out_of_range", "frozen"]
NodeStatus = Literal["normal", "suspect", "affected", "origin"]
NodeKind = Literal["sensor", "actuator", "controller"]
Mode = Literal["sim", "hai", "live"]
IncidentStatus = Literal["localizing", "open", "closed", "contained"]


# ---------------------------------------------------------------------------- live stream
class NodeState(BaseModel):
    id: str
    value: float  # as reported to SCADA (may be spoofed)
    truth: float | None  # physical truth (SIM only)
    score: float  # smoothed normalized forecast error
    status: NodeStatus
    quality: Quality | None = None  # Phase 13: LIVE data quality; None in SIM and HAI


class AlertInfo(BaseModel):
    since: float  # unix time the alert started
    score: float  # current top-k aggregate score
    threshold: float


class Triple(BaseModel):
    """One value per localization signal."""

    deviation: float
    onset: float
    causal: float


class OriginCandidate(BaseModel):
    id: str
    type: NodeKind
    confidence: float  # softmax over scores, sums to 1 across all candidates
    # Phase 11 (additive): this node's own contributions weight*term (they sum to its raw score,
    # which differs from the ranked score only inside a tie group) and the weights used.
    breakdown: Triple | None = None
    weights: Triple | None = None


class PathStep(BaseModel):
    id: str
    t: float  # seconds after the first onset
    deviation: float


class GroundTruthInfo(BaseModel):
    """Revealed by the UI after localization (SIM only)."""

    attack_id: str
    scenario: Scenario
    target: str
    started_at: float
    mitre: str


class Incident(BaseModel):
    id: str
    status: IncidentStatus
    detected_at: float
    origin: list[OriginCandidate]  # top-3, best first
    path: list[PathStep]  # deviating nodes in onset order
    path_edges: list[tuple[str, str]]
    explanation: str
    action: str
    mitre: str
    mitre_name: str
    baseline_alarms: list[str]  # what the 3-sigma baseline would be flashing
    ground_truth: GroundTruthInfo | None = None
    mode: Mode = "sim"  # Phase 13: which source produced the incident
    ambiguous: bool = False  # Phase 11: top-1 and top-2 confidence are too close to trust one
    contained_at: float | None = None  # unix time the isolate action took effect (SIM only)
    time_to_contain_s: float | None = None  # plant seconds from the isolate action to containment
    isolated_by: str | None = None  # operator name attached to the accepted isolate request, if any


class Impact(BaseModel):
    t1_overflow_s: float | None
    t1_dry_s: float | None
    t2_overflow_s: float | None
    t2_dry_s: float | None
    pump_stress: dict[str, float]
    energy_wasted_kwh: float


class LiveMessage(BaseModel):
    t: float  # unix time of emission
    mode: Mode
    nodes: list[NodeState]
    alert: AlertInfo | None
    incident: Incident | None  # derived: incidents[0] if any (most severe), else None
    incidents: list[Incident] = []  # Phase 15+: every currently-open incident, severity-sorted
    impact: Impact | None
    source_latency_ms: float | None = None  # Phase 13: age of the newest LIVE sample at emit time


# ---------------------------------------------------------------------------------- REST
SourceState = Literal["connected", "stale", "connecting", "down", "calibrating"]


class SourceInfo(BaseModel):
    """Where the data comes from and how healthy that link is (Phase 13)."""

    mode: Mode
    connected: bool
    protocol: str  # "internal" (SIM), "replay" (HAI), "modbus" (LIVE)
    state: SourceState
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    samples_per_s: float = 0.0
    dropped: int = 0
    reason: str | None = None  # why it is not connected, or which tags are faulty
    progress: float | None = None  # 0..1 while state is "calibrating"


class TagHealth(BaseModel):
    tag: str
    node_id: str
    quality: Quality
    age_ms: float | None
    last_value: float | None


class Status(BaseModel):
    mode: Mode
    hai_available: bool
    detector_active: str | None  # "gdn" | "mlp" | None when no model is loaded
    uptime_s: float
    source: SourceInfo | None = None  # Phase 13
    live_available: bool = False  # Phase 13: the LIVE source answers right now
    live_reason: str | None = None  # Phase 13: why LIVE is not available


class ModeRequest(BaseModel):
    mode: Mode


class AttackRequest(BaseModel):
    scenario: Scenario
    target: str
    magnitude: float = 0.0  # meaning depends on scenario, see attacks.AttackSpec
    duration_s: float = Field(default=60.0, gt=0, le=3600)


class AttackResponse(BaseModel):
    attack_id: str


class IsolateRequest(BaseModel):
    incident_id: str
    node_id: str
    operator: str | None = None  # who issued the action; attached to the incident and the report


class IsolateResponse(BaseModel):
    accepted: bool  # the action was applied; containment is reported later by incident.status
    reason: str | None = None


class TopologyNode(BaseModel):
    id: str
    type: NodeKind
    label: str
    unit: str
    lo: float
    hi: float


class TopologyEdge(BaseModel):
    src: str
    dst: str
    weight: float
    kind: Literal["static", "learned"]


class Topology(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: Literal["operator", "analyst"]
    expires_in_s: float


class HistorySample(BaseModel):
    t: float
    value: float
    score: float
    status: str
