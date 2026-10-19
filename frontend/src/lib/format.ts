import type { TopologyNode } from "./types";

/** Display value for a node: levels in %, flow L/s, pressure bar, actuators and PLCs in %. */
export function formatValue(id: string, v: number): string {
  if (id.startsWith("LIT")) return `${v.toFixed(1)}%`;
  if (id.startsWith("FIT")) return `${v.toFixed(2)} L/s`;
  if (id.startsWith("PIT")) return `${v.toFixed(2)} bar`;
  if (SIM_FRACTION.test(id)) return `${Math.round(v * 100)}%`;
  return plain(v); // HAI tags: raw engineering units
}

/** SIM actuators and PLC outputs are 0..1 fractions shown as percent. */
const SIM_FRACTION = /^(MV\d+|P\d{3}|PLC\d)$/;

/** Compact number for unknown units: more digits for small values. */
export function plain(v: number): string {
  const a = Math.abs(v);
  return a >= 1000 ? v.toFixed(0) : a >= 100 ? v.toFixed(1) : v.toFixed(2);
}

/** True when a reported sensor value differs from physical truth by more than 3% of its range. */
export function isSpoofed(node: TopologyNode | undefined, value: number, truth: number | null): boolean {
  if (!node || truth === null || node.type !== "sensor") return false;
  return Math.abs(value - truth) > 0.03 * (node.hi - node.lo);
}

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

/** ETA seconds → label: "134 s", "4 m", or an en dash when there is no risk. */
export function formatEta(s: number | null): string {
  if (s === null) return "–";
  return s < 100 ? `${Math.round(s)} s` : `${Math.round(s / 60)} m`;
}

/** 0 (no risk) … 1 (imminent) over the backend's 300 s reporting horizon. */
export function etaUrgency(s: number | null, horizon = 300): number {
  return s === null ? 0 : clamp01(1 - s / horizon);
}
