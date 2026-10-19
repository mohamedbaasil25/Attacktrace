/** Shape of reports/metrics.json as written by `make eval` (see backend/eval/run.py). */
export interface DetectorMetrics {
  precision: number;
  recall: number;
  f1: number;
  false_alarm_per_hour: number;
  mean_detection_delay_s: number | null;
  per_scenario: Record<string, { f1: number; recall: number; runs_detected: number }>;
}

export interface LocalizationMetrics {
  top1: number;
  top3: number;
  mean_time_to_localize_s: number | null;
  /** Earliest-3-sigma-breach ranking, same protocol; absent in older metrics.json files. */
  baseline?: { top1: number; top3: number };
}

export interface HaiDetectorMetrics {
  precision: number;
  recall: number;
  f1: number;
  f1_point_adjusted: number;
  false_alarm_per_hour: number;
  windows_detected: number;
  n_windows: number;
}

/** Real-data section written by `make eval` when HAI files are present. */
export interface HaiMetrics {
  files: string[];
  tuned_on: string;
  active_model: string;
  attacktrace: HaiDetectorMetrics;
  baseline: HaiDetectorMetrics;
  localization: {
    process_top1: number;
    process_top1_given_detected: number | null;
    always_majority_given_detected: number | null;
    always_majority_process: number;
    majority_process: string;
    n_windows: number;
    n_detected: number;
  };
}

/** Phase 11 blocks; absent in metrics.json files written before the confidence gate. */
export interface AmbiguityMetrics {
  gate_margin: number;
  n_incidents: number;
  n_ambiguous: number;
  ambiguous_rate: number;
}

export interface IsolationMetrics {
  n_detected: number;
  isolate_top1: { n: number; contained: number; success_rate: number };
}

/** Phase 13 Part F: written by `make eval-live` to reports/live_metrics.json, merged into
 *  /api/metrics as `live`. Absent until that eval has run once. */
export interface LiveEvalMetrics {
  detection: { precision: number; recall: number; f1: number; false_alarm_per_hour: number };
  localization: { top1: number; top3: number };
  latency_ms: { p50: number; p95: number; p99: number };
  samples_per_s: number;
  dropped: number;
  n_attacks: number;
  n_clean_runs: number;
  uptime_s: number | null;
}

/** The currently-running session's own false-alarm rate, merged in at response time by
 *  `GET /api/metrics` (never written to metrics.json). SIM and LIVE only -- HAI incidents carry
 *  no ground truth by design, so the "false alarm = no ground truth" heuristic doesn't apply. */
export interface LiveSessionMetrics {
  mode: "sim" | "live";
  uptime_s: number;
  false_alarm_per_hour: number;
}

export interface Metrics {
  ambiguity?: AmbiguityMetrics;
  isolation?: IsolationMetrics;
  detection: { attacktrace: DetectorMetrics; baseline: DetectorMetrics; active_model?: string };
  localization: LocalizationMetrics;
  hai?: HaiMetrics;
  live?: LiveEvalMetrics;
  live_session?: LiveSessionMetrics;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

function detector(v: unknown): DetectorMetrics | null {
  if (!isObj(v) || !isObj(v.per_scenario)) return null;
  if (![v.precision, v.recall, v.f1, v.false_alarm_per_hour].every(isNum)) return null;
  return v as unknown as DetectorMetrics;
}

function haiDetector(v: unknown): boolean {
  if (!isObj(v)) return false;
  const keys = ["precision", "recall", "f1", "f1_point_adjusted", "false_alarm_per_hour", "windows_detected", "n_windows"];
  return keys.every((k) => isNum(v[k]));
}

/** The HAI section is optional; a malformed one is dropped instead of failing the page. */
function parseHai(v: unknown): HaiMetrics | undefined {
  if (!isObj(v) || !haiDetector(v.attacktrace) || !haiDetector(v.baseline)) return undefined;
  const loc = v.localization;
  if (!isObj(loc) || !isNum(loc.process_top1) || !isNum(loc.always_majority_process)) return undefined;
  if (!Array.isArray(v.files)) return undefined;
  return v as unknown as HaiMetrics;
}

function parseAmbiguity(v: unknown): AmbiguityMetrics | undefined {
  if (!isObj(v) || ![v.gate_margin, v.n_incidents, v.n_ambiguous, v.ambiguous_rate].every(isNum)) {
    return undefined;
  }
  return v as unknown as AmbiguityMetrics;
}

function parseIsolation(v: unknown): IsolationMetrics | undefined {
  if (!isObj(v) || !isNum(v.n_detected) || !isObj(v.isolate_top1)) return undefined;
  const t = v.isolate_top1;
  if (![t.n, t.contained, t.success_rate].every(isNum)) return undefined;
  return v as unknown as IsolationMetrics;
}

function parseLive(v: unknown): LiveEvalMetrics | undefined {
  if (!isObj(v) || !isObj(v.detection) || !isObj(v.localization) || !isObj(v.latency_ms)) {
    return undefined;
  }
  const d = v.detection;
  const l = v.localization;
  const lat = v.latency_ms;
  if (![d.precision, d.recall, d.f1, d.false_alarm_per_hour].every(isNum)) return undefined;
  if (![l.top1, l.top3].every(isNum)) return undefined;
  if (![lat.p50, lat.p95, lat.p99].every(isNum)) return undefined;
  if (!isNum(v.samples_per_s) || !isNum(v.dropped)) return undefined;
  return v as unknown as LiveEvalMetrics;
}

function parseLiveSession(v: unknown): LiveSessionMetrics | undefined {
  if (!isObj(v) || !isNum(v.uptime_s) || !isNum(v.false_alarm_per_hour)) return undefined;
  if (v.mode !== "sim" && v.mode !== "live") return undefined;
  return v as unknown as LiveSessionMetrics;
}

/** Validates the parts the metrics page reads; null when the file is incomplete. */
export function parseMetrics(raw: unknown): Metrics | null {
  if (!isObj(raw) || !isObj(raw.detection) || !isObj(raw.localization)) return null;
  const attacktrace = detector(raw.detection.attacktrace);
  const baseline = detector(raw.detection.baseline);
  const loc = raw.localization;
  if (!attacktrace || !baseline || !isNum(loc.top1) || !isNum(loc.top3)) return null;
  return {
    ...(raw as unknown as Metrics),
    hai: parseHai(raw.hai),
    ambiguity: parseAmbiguity(raw.ambiguity),
    isolation: parseIsolation(raw.isolation),
    live: parseLive(raw.live),
    live_session: parseLiveSession(raw.live_session),
  };
}

export const SCENARIO_SHORT: Record<string, string> = {
  sensor_freeze: "Freeze",
  sensor_offset: "Offset",
  sensor_ramp: "Ramp",
  actuator_force: "Force",
  rogue_setpoint: "Setpoint",
};

export interface BarRow {
  label: string;
  baseline: number;
  attacktrace: number;
}

/** Overall F1 first, then F1 per scenario, for the grouped bar chart. */
export function f1Rows(m: Metrics): BarRow[] {
  const { attacktrace: a, baseline: b } = m.detection;
  const rows: BarRow[] = [{ label: "Overall", baseline: b.f1, attacktrace: a.f1 }];
  for (const [key, label] of Object.entries(SCENARIO_SHORT)) {
    const sa = a.per_scenario[key];
    const sb = b.per_scenario[key];
    if (sa && sb) rows.push({ label, baseline: sb.f1, attacktrace: sa.f1 });
  }
  return rows;
}

export const pct = (x: number): string => `${(x * 100).toFixed(0)}%`;
