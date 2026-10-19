import { create } from "zustand";
import { REPLAY_LEAD, clampIndex, incidentStartIndex, stepCursor } from "../lib/replay";
import type { Incident, LiveMessage, Status, TagHealth, Topology, TopologyNode } from "../lib/types";
import type { ConnState } from "../lib/ws";

/** 5 minutes of history at the 500 ms emit period. */
export const RING_CAPACITY = 600;

export function pushRing<T>(buf: readonly T[], item: T, cap: number = RING_CAPACITY): T[] {
  const next = buf.length >= cap ? buf.slice(buf.length - cap + 1) : buf.slice();
  next.push(item);
  return next;
}

interface LiveState {
  conn: ConnState;
  buffer: LiveMessage[];
  latest: LiveMessage | null;
  receivedAt: number | null; // Date.now() of the latest message
  status: Status | null;
  topology: Topology | null;
  /** Per-tag LIVE quality and age (Phase 13); null outside LIVE mode. */
  liveHealth: TagHealth[] | null;
  /** Replay position as a buffer index; null follows the live stream. */
  cursor: number | null;
  playing: boolean;
  setConn: (c: ConnState) => void;
  push: (m: LiveMessage, nowMs?: number) => void;
  setStatus: (s: Status) => void;
  setTopology: (t: Topology) => void;
  setLiveHealth: (h: TagHealth[]) => void;
  clear: () => void;
  scrubTo: (index: number) => void;
  pause: () => void;
  play: () => void;
  goLive: () => void;
  replayIncident: () => void;
  tick: () => void;
}

export const useLive = create<LiveState>((set) => ({
  conn: "connecting",
  buffer: [],
  latest: null,
  receivedAt: null,
  status: null,
  topology: null,
  liveHealth: null,
  cursor: null,
  playing: false,
  setConn: (conn) => set({ conn }),
  push: (m, nowMs = Date.now()) =>
    set((s) => {
      const full = s.buffer.length >= RING_CAPACITY;
      // When the ring drops its oldest sample every index shifts down by one.
      const cursor = s.cursor === null ? null : full ? Math.max(0, s.cursor - 1) : s.cursor;
      return { buffer: pushRing(s.buffer, m), latest: m, receivedAt: nowMs, cursor };
    }),
  setStatus: (status) => set({ status }),
  setTopology: (topology) => set({ topology }),
  setLiveHealth: (liveHealth) => set({ liveHealth }),
  clear: () =>
    set({ buffer: [], latest: null, receivedAt: null, cursor: null, playing: false, liveHealth: null }),
  scrubTo: (index) =>
    set((s) => (s.buffer.length ? { cursor: clampIndex(index, s.buffer.length), playing: false } : s)),
  pause: () =>
    set((s) => (s.buffer.length ? { cursor: s.cursor ?? s.buffer.length - 1, playing: false } : s)),
  play: () => set((s) => (s.cursor === null ? s : { playing: true })),
  goLive: () => set({ cursor: null, playing: false }),
  replayIncident: () =>
    set((s) => {
      const start = incidentStartIndex(s.buffer);
      return start === null ? s : { cursor: Math.max(0, start - REPLAY_LEAD), playing: true };
    }),
  tick: () =>
    set((s) => {
      const cursor = stepCursor(s.cursor, s.buffer.length);
      return { cursor, playing: cursor !== null && s.playing };
    }),
}));

/** The message every view renders: the replay cursor's sample, or the live one. */
export function selectView(s: Pick<LiveState, "cursor" | "buffer" | "latest">): LiveMessage | null {
  return s.cursor === null ? s.latest : (s.buffer[s.cursor] ?? s.latest);
}

/** Every currently-open incident on the selected message, severity-sorted by the backend. */
export function selectIncidents(s: Pick<LiveState, "cursor" | "buffer" | "latest">): Incident[] {
  return selectView(s)?.incidents ?? [];
}

/** id → topology node, for ranges and units. Empty until /api/topology has loaded. */
export function nodeMap(topology: Topology | null): Map<string, TopologyNode> {
  return new Map((topology?.nodes ?? []).map((n) => [n.id, n]));
}
