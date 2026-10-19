import { isActive } from "./incident";
import type { LiveMessage } from "./types";
import type { ConnState } from "./ws";

export type PillKind = "connecting" | "offline" | "normal" | "alert" | "incident";

/** One state for the top-bar pill: connection first, then the plant's alert level. */
export function pillKind(conn: ConnState, msg: LiveMessage | null): PillKind {
  if (conn === "connecting") return "connecting";
  if (conn === "reconnecting") return "offline";
  if (isActive(msg?.incident)) return "incident";
  if (msg?.alert) return "alert";
  return "normal";
}

export const PILL_LABEL: Record<PillKind, string> = {
  connecting: "Connecting",
  offline: "Reconnecting",
  normal: "Normal",
  alert: "Alert",
  incident: "Incident",
};

/** Client-side latency in ms from a server timestamp (unix seconds); never negative. */
export function latencyMs(serverT: number, nowMs: number): number {
  return Math.max(0, Math.round(nowMs - serverT * 1000));
}
