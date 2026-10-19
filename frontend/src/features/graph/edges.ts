import { PULSE_STAGGER_S } from "../twin/geometry";
import { isActive } from "../../lib/incident";
import type { Incident, TopologyEdge } from "../../lib/types";

/** Learned (Granger) edges below this weight stay hidden, matching the detector's attention mask. */
export const MIN_LEARNED_WEIGHT = 0.25;

export const edgeId = (e: Pick<TopologyEdge, "src" | "dst">): string => `${e.src}->${e.dst}`;

/** SIM: every P&ID edge plus the strong learned ones. A plant without a P&ID (HAI) has only
 *  learned edges, already sparse, so all of them are shown. */
export const visibleEdges = (edges: readonly TopologyEdge[]): TopologyEdge[] =>
  edges.some((e) => e.kind === "static")
    ? edges.filter((e) => e.kind === "static" || e.weight >= MIN_LEARNED_WEIGHT)
    : [...edges];

/** Edges that drive the layout: the P&ID when there is one, otherwise the learned edges. */
export const layoutEdges = (edges: readonly TopologyEdge[]): TopologyEdge[] =>
  edges.some((e) => e.kind === "static") ? edges.filter((e) => e.kind === "static") : [...edges];

/**
 * Delay (s) before the attack pulse runs along src->dst, or null when the edge is not on the
 * incident path. The delay is the source node's onset plus its position in the path, so pulses
 * follow onset order and stay sequential for nodes that deviate within one sample.
 */
export function edgeDelay(
  src: string,
  dst: string,
  incident: Incident | null | undefined,
): number | null {
  if (!isActive(incident)) return null;
  if (!incident.path_edges.some(([a, b]) => a === src && b === dst)) return null;
  const i = incident.path.findIndex((p) => p.id === src);
  const step = incident.path[i];
  return step ? step.t + i * PULSE_STAGGER_S : 0;
}
