import type { LiveMessage } from "./types";

/** Samples shown before the incident when replaying it (20 s at 2 Hz). */
export const REPLAY_LEAD = 40;

export const clampIndex = (i: number, len: number): number => Math.min(Math.max(i, 0), len - 1);

/** Next playback cursor; returns null (back to live) once playback reaches the newest sample. */
export function stepCursor(cursor: number | null, len: number): number | null {
  if (cursor === null) return null;
  const next = cursor + 1;
  return next >= len ? null : next;
}

/** Index of the first buffered message that carries the newest incident, or null. */
export function incidentStartIndex(buffer: readonly LiveMessage[]): number | null {
  let id: string | undefined;
  for (let i = buffer.length - 1; i >= 0 && !id; i--) id = buffer[i]?.incident?.id;
  if (!id) return null;
  const i = buffer.findIndex((m) => m.incident?.id === id);
  return i < 0 ? null : i;
}

/** Timeline x for a sample. The oldest sample sits at the left edge, level with the labels; a
 *  short buffer leaves empty space on the right, so the axis never rescales while data streams in. */
export function indexToX(i: number, _len: number, cap: number, width: number): number {
  return (i / (cap - 1)) * width;
}

export function xToIndex(x: number, len: number, cap: number, width: number): number {
  return clampIndex(Math.round((x / width) * (cap - 1)), len);
}

/** SVG path for a series, scaled into [0,w]x[0,h] (y grows downward). */
export function seriesPath(
  values: readonly number[],
  cap: number,
  w: number,
  h: number,
  min: number,
  max: number,
): string {
  const span = max - min || 1;
  return values
    .map((v, i) => {
      const x = indexToX(i, values.length, cap, w);
      const y = h - ((v - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export interface Marker {
  index: number;
  kind: "detected" | "attack";
  label: string;
}

/** Timeline markers: when each incident was detected and when each attack was launched. */
export function markers(buffer: readonly LiveMessage[]): Marker[] {
  const out: Marker[] = [];
  const seen = new Set<string>();
  buffer.forEach((m, index) => {
    const inc = m.incident;
    if (inc && !seen.has(inc.id)) {
      seen.add(inc.id);
      out.push({ index, kind: "detected", label: `${inc.id} detected` });
    }
    const gt = inc?.ground_truth;
    if (gt && !seen.has(gt.attack_id)) {
      seen.add(gt.attack_id);
      const at = buffer.findIndex((b) => b.t >= gt.started_at);
      out.push({ index: at < 0 ? index : at, kind: "attack", label: `${gt.attack_id} launched` });
    }
  });
  return out;
}

/** Per-node [reported, truth] series over the buffer; truth falls back to the reported value. */
export function nodeSeries(
  buffer: readonly LiveMessage[],
  id: string,
): { reported: number[]; truth: number[] } {
  const reported: number[] = [];
  const truth: number[] = [];
  for (const m of buffer) {
    const n = m.nodes.find((x) => x.id === id);
    if (!n) continue;
    reported.push(n.value);
    truth.push(n.truth ?? n.value);
  }
  return { reported, truth };
}

const SIM_ROWS = ["LIT101", "FIT201", "PIT301", "LIT301"];
const HAI_ROWS = ["P1_LIT01", "P1_FT01", "P1_PIT01", "P3_LT01"];

/** The four sparkline rows: the SIM sensors, or HAI's level/flow/pressure tags (padded from the
 *  node list when a tag is missing). */
export function timelineRows(ids: readonly string[]): string[] {
  const have = new Set(ids);
  if (SIM_ROWS.every((r) => have.has(r))) return SIM_ROWS;
  const rows = HAI_ROWS.filter((r) => have.has(r));
  for (const id of ids) if (rows.length < 4 && !rows.includes(id)) rows.push(id);
  return rows.slice(0, 4);
}
