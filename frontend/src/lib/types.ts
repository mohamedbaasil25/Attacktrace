// Mirrors backend/app/schemas.py. FROZEN after Phase 4: change both together, with approval.
// `incidents` (Phase 15+) is an additive exception: `incident` is unchanged in shape but is
// now derived from `incidents` (most severe, or null).
export type NodeStatus = "normal" | "suspect" | "affected" | "origin";
export type NodeKind = "sensor" | "actuator" | "controller";
export type Mode = "sim" | "hai" | "live";
export type Quality = "good" | "stale" | "missing" | "out_of_range" | "frozen";
export type IncidentStatus = "localizing" | "open" | "closed" | "contained";
export type Scenario =
  | "sensor_freeze"
  | "sensor_offset"
  | "sensor_ramp"
  | "actuator_force"
  | "rogue_setpoint";

// ---- live stream (/ws/live, one message every 500 ms)
export interface NodeState {
  id: string;
  value: number; // as reported to SCADA (may be spoofed)
  truth: number | null; // physical truth (SIM only)
  score: number;
  status: NodeStatus;
  quality?: Quality | null; // Phase 13: LIVE data quality; absent in SIM and HAI
}

export interface AlertInfo {
  since: number; // unix seconds
  score: number;
  threshold: number;
}

export interface Triple {
  deviation: number;
  onset: number;
  causal: number;
}

export interface OriginCandidate {
  id: string;
  type: NodeKind;
  confidence: number;
  /** Phase 11: this node's own weight*term contributions and the weights used. */
  breakdown?: Triple | null;
  weights?: Triple | null;
}

export interface PathStep {
  id: string;
  t: number; // seconds after the first onset
  deviation: number;
}

export interface GroundTruthInfo {
  attack_id: string;
  scenario: Scenario;
  target: string;
  started_at: number;
  mitre: string;
}

export interface Incident {
  id: string;
  status: IncidentStatus;
  detected_at: number;
  origin: OriginCandidate[]; // top-3, best first
  path: PathStep[];
  path_edges: [string, string][];
  explanation: string;
  action: string;
  mitre: string;
  mitre_name: string;
  baseline_alarms: string[];
  ground_truth: GroundTruthInfo | null;
  mode?: Mode; // Phase 13: which source produced the incident
  ambiguous?: boolean; // Phase 11: top-1 and top-2 confidence too close to trust one
  contained_at?: number | null; // unix time the isolate action took effect (SIM only)
  time_to_contain_s?: number | null; // plant seconds from the isolate action to containment
  isolated_by?: string | null; // operator name attached to the accepted isolate request, if any
}

export interface Impact {
  t1_overflow_s: number | null;
  t1_dry_s: number | null;
  t2_overflow_s: number | null;
  t2_dry_s: number | null;
  pump_stress: Record<string, number>;
  energy_wasted_kwh: number;
}

export interface LiveMessage {
  t: number;
  mode: Mode;
  nodes: NodeState[];
  alert: AlertInfo | null;
  incident: Incident | null; // derived: incidents[0] if any (most severe), else null
  incidents: Incident[]; // Phase 15+: every currently-open incident, severity-sorted
  impact: Impact | null;
  source_latency_ms?: number | null; // Phase 13: age of the newest LIVE sample
}

// ---- REST
export type SourceState = "connected" | "stale" | "connecting" | "down" | "calibrating";

export interface SourceInfo {
  mode: Mode;
  connected: boolean;
  protocol: string; // internal (SIM), replay (HAI), modbus (LIVE)
  state: SourceState;
  latency_ms_p50?: number | null;
  latency_ms_p95?: number | null;
  samples_per_s?: number;
  dropped?: number;
  reason?: string | null; // why it is not connected, or which tags are faulty
  progress?: number | null; // 0..1 while calibrating
}

export interface TagHealth {
  tag: string;
  node_id: string;
  quality: Quality;
  age_ms: number | null;
  last_value: number | null;
}

export interface Status {
  mode: Mode;
  hai_available: boolean;
  detector_active: string | null;
  uptime_s: number;
  source?: SourceInfo | null; // Phase 13
  live_available?: boolean; // Phase 13: the LIVE source answers right now
  live_reason?: string | null;
  /** Production Transition Roadmap, Phase 1: AT_AUTH_SECRET is configured server-side, so a
   *  verified login (not just the operator-name field) is required before Isolate. */
  auth_required?: boolean;
  /** Phase 5: the incidents+audit-ledger store opened successfully. The app runs in degraded
   *  mode (no persistence, no evidence) rather than crash when this is false -- distinct from
   *  general app health, since a 200 here does not mean evidence is being preserved. */
  evidence_available?: boolean;
}

export interface AttackRequest {
  scenario: Scenario;
  target: string;
  magnitude?: number;
  duration_s?: number;
}

export interface AttackResponse {
  attack_id: string;
}

export interface TopologyNode {
  id: string;
  type: NodeKind;
  label: string;
  unit: string;
  lo: number;
  hi: number;
}

export interface TopologyEdge {
  src: string;
  dst: string;
  weight: number;
  kind: "static" | "learned";
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface IsolateRequest {
  incident_id: string;
  node_id: string;
  operator?: string;
}

export interface IsolateResponse {
  accepted: boolean; // applied; containment is reported later by incident.status
  reason?: string | null;
}

export interface LoginResponse {
  token: string;
  username: string;
  role: "operator" | "analyst";
  expires_in_s: number;
}

/** One retained sample from the tag-level historian (GET /api/history), independent of the
 *  engine's own 5-minute in-memory ring buffer. */
export interface HistorySample {
  t: number;
  value: number;
  score: number;
  status: string;
}

export interface VerificationIssue {
  seq: number | null;
  kind: string;
  detail: string;
}

export interface VerifyLedgerResponse {
  status: "verified" | "integrity_failure" | "unavailable";
  checked: number;
  first_failure: VerificationIssue | null;
  issue_count: number;
}
