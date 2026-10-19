import type { NodeState, PathStep } from "../../lib/types";
import { clamp01 } from "../../lib/format";

// Phase 14 C4: h was 520, but all content (badges, tanks, the filter) sits within y ~13-400, so
// the bottom ~120 units were pure unused margin. Trimming it to 400 raises the split-view
// mini-twin's effective scale with no coordinate changes (nothing below y=400 ever existed) --
// verified empirically across 1280x800, 1366x768, 1440x900 and 1920x1080.
export const VIEW = { w: 900, h: 400 } as const;

/** SVG text size in view units: the twin is drawn at 0.74x at the narrowest layout (1280 px), so
 *  16.5 units render at about 12 px there. */
export const TEXT = 16.5;
export const CHAR_W = TEXT * 0.6; // monospace advance

export interface Pt {
  x: number;
  y: number;
}

export const TANKS = {
  T1: { x: 120, y: 120, w: 130, h: 230, node: "LIT101" },
  T2: { x: 610, y: 120, w: 130, h: 230, node: "LIT301" },
} as const;

/** Where each node sits; badges are drawn centred on these points. */
export const ANCHOR = {
  PLC1: { x: 185, y: 36 },
  PLC2: { x: 675, y: 36 },
  MV101: { x: 65, y: 170 },
  LIT101: { x: 307, y: 144 },
  P101: { x: 330, y: 310 },
  FIT201: { x: 390, y: 250 },
  PIT301: { x: 495, y: 216 },
  LIT301: { x: 797, y: 144 },
  P301: { x: 800, y: 310 },
} as const satisfies Record<string, Pt>;

export const anchorOf = (id: string): Pt | undefined => (ANCHOR as Record<string, Pt>)[id];

export const FILTER = { x: 440, y: 260, w: 110, h: 100 } as const;

type Edge = [string, string];

export interface Link {
  id: string;
  kind: "pipe" | "control";
  d: string;
  /** P&ID edges this drawn line stands for (used to light it up along the attack path). */
  edges: Edge[];
  /** Which node's physical value sets the flow speed (pipes only). */
  flow?: { node: string; scale: number };
}

export const LINKS: readonly Link[] = [
  {
    id: "in",
    kind: "pipe",
    d: "M10 170 H120",
    edges: [["MV101", "LIT101"]],
    flow: { node: "MV101", scale: 1 },
  },
  {
    id: "t1",
    kind: "pipe",
    d: "M250 310 H304",
    edges: [["P101", "LIT101"]],
    flow: { node: "FIT201", scale: 12 },
  },
  {
    id: "f1",
    kind: "pipe",
    d: "M356 310 H440",
    edges: [
      ["P101", "FIT201"],
      ["LIT101", "FIT201"],
    ],
    flow: { node: "FIT201", scale: 12 },
  },
  {
    id: "t2",
    kind: "pipe",
    d: "M550 310 H610",
    edges: [
      ["FIT201", "LIT301"],
      ["FIT201", "PIT301"],
    ],
    flow: { node: "FIT201", scale: 12 },
  },
  {
    id: "o1",
    kind: "pipe",
    d: "M740 310 H774",
    edges: [["P301", "LIT301"]],
    flow: { node: "P301", scale: 1 },
  },
  {
    id: "o2",
    kind: "pipe",
    d: "M826 310 H890",
    edges: [["P301", "LIT301"]],
    flow: { node: "P301", scale: 1 },
  },
  { id: "c1", kind: "control", d: "M307 124 L185 58", edges: [["LIT101", "PLC1"]] },
  { id: "c2", kind: "control", d: "M185 58 L65 150", edges: [["PLC1", "MV101"]] },
  { id: "c3", kind: "control", d: "M185 58 L330 284", edges: [["PLC1", "P101"]] },
  { id: "c4", kind: "control", d: "M797 124 L675 58", edges: [["LIT301", "PLC2"]] },
  { id: "c5", kind: "control", d: "M675 58 L800 284", edges: [["PLC2", "P301"]] },
];

/** 0..1 flow strength of a pipe from the physical truth of its driving node. */
export function flowRatio(link: Link, nodes: ReadonlyMap<string, NodeState>): number {
  if (!link.flow) return 0;
  const n = nodes.get(link.flow.node);
  return clamp01(((n?.truth ?? n?.value) ?? 0) / link.flow.scale);
}

/** Seconds per dash cycle, or null when nothing is flowing. */
export function flowDuration(ratio: number): number | null {
  return ratio < 0.02 ? null : 2.4 - 1.8 * clamp01(ratio);
}

/** Seconds per impeller turn, or null when the pump is stopped. */
export function spinDuration(speed: number): number | null {
  return speed < 0.02 ? null : 2 - 1.6 * clamp01(speed);
}

/** Extra delay per path position: nodes that deviate within one 0.5 s sample still pulse in order. */
export const PULSE_STAGGER_S = 0.15;

/**
 * Delay (s) before an attack pulse runs along this link, or null if the link is not on the
 * incident path. The delay is the onset of the edge's source node plus its position in the
 * path, which the backend orders by onset and then cause-before-effect.
 */
export function pulseDelay(
  link: Link,
  pathEdges: readonly Edge[],
  path: readonly PathStep[],
): number | null {
  const slot = new Map(path.map((p, i) => [p.id, p.t + i * PULSE_STAGGER_S]));
  const hit = link.edges.filter(([a, b]) => pathEdges.some(([x, y]) => x === a && y === b));
  if (hit.length === 0) return null;
  return Math.min(...hit.map(([a]) => slot.get(a) ?? 0));
}
