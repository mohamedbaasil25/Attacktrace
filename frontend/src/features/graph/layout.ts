export interface LayoutEdge {
  src: string;
  dst: string;
}

export interface Pos {
  x: number;
  y: number;
}

/**
 * Left-to-right layered layout (dagre-style, computed in-house).
 * 1. Drop feedback edges found by DFS so the P&ID loops become a DAG.
 * 2. Layer by longest path from the sources.
 * 3. Order each layer by the barycentre of its predecessors (two sweeps) to cut crossings.
 */
export function layerLayout(
  ids: readonly string[],
  edges: readonly LayoutEdge[],
  dx = 170,
  dy = 100,
): Record<string, Pos> {
  const out = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of edges) if (out.has(e.src) && out.has(e.dst) && e.src !== e.dst) out.get(e.src)?.push(e.dst);

  const state = new Map<string, 0 | 1 | 2>(); // 1 = on the DFS stack, 2 = done
  const forward: LayoutEdge[] = [];
  const visit = (u: string) => {
    state.set(u, 1);
    for (const v of out.get(u) ?? []) {
      if (state.get(v) === 1) continue; // feedback edge
      forward.push({ src: u, dst: v });
      if (!state.has(v)) visit(v);
    }
    state.set(u, 2);
  };
  for (const id of ids) if (!state.has(id)) visit(id);

  const preds = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of forward) preds.get(e.dst)?.push(e.src);
  const layer = new Map<string, number>();
  const depth = (id: string): number => {
    const known = layer.get(id);
    if (known !== undefined) return known;
    const l = Math.max(-1, ...(preds.get(id) ?? []).map(depth)) + 1;
    layer.set(id, l);
    return l;
  };
  ids.forEach(depth);

  const columns: string[][] = [];
  for (const id of ids) (columns[layer.get(id) ?? 0] ??= []).push(id);
  const rank = (id: string): number => columns.flat().indexOf(id);
  for (let sweep = 0; sweep < 2; sweep++) {
    columns.forEach((col, l) => {
      if (l === 0) return;
      const pos = new Map(columns[l - 1]?.map((id, i) => [id, i]));
      const bary = (id: string) => {
        const p = (preds.get(id) ?? []).map((q) => pos.get(q)).filter((v): v is number => v !== undefined);
        return p.length ? p.reduce((a, b) => a + b, 0) / p.length : rank(id);
      };
      col.sort((a, b) => bary(a) - bary(b));
    });
  }

  const result: Record<string, Pos> = {};
  columns.forEach((col, l) =>
    col.forEach((id, i) => {
      result[id] = { x: l * dx, y: (i - (col.length - 1) / 2) * dy };
    }),
  );
  return result;
}

/** Group key for a HAI tag ("P1_LIT01" -> "P1"); other ids share one group. */
export const processOf = (id: string): string => /^(P\d)_/.exec(id)?.[1] ?? "?";

/**
 * Compact layout for a plant without a P&ID: one block per process (sorted), each wrapped into
 * columns of `perColumn` nodes. A layered layout of ~50 learned edges is a very long strip.
 */
export function groupLayout(
  ids: readonly string[],
  groupOf: (id: string) => string = processOf,
  perColumn = 10,
  dx = 132,
  dy = 62,
  gap = 56,
): Record<string, Pos> {
  const result: Record<string, Pos> = {};
  let x = 0;
  for (const g of [...new Set(ids.map(groupOf))].sort()) {
    const members = ids.filter((id) => groupOf(id) === g);
    const rows = Math.min(members.length, perColumn);
    members.forEach((id, i) => {
      result[id] = { x: x + Math.floor(i / perColumn) * dx, y: ((i % perColumn) - (rows - 1) / 2) * dy };
    });
    x += Math.ceil(members.length / perColumn) * dx + gap;
  }
  return result;
}
