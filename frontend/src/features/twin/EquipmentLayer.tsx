import type { NodeState, TopologyNode } from "../../lib/types";
import { Pump, Tank, Valve } from "./Equipment";
import { ANCHOR, FILTER, TANKS, TEXT, anchorOf } from "./geometry";
import { NodeBadge } from "./NodeBadge";

interface Props {
  nodes: ReadonlyMap<string, NodeState>;
  topo: ReadonlyMap<string, TopologyNode>;
  /** LIVE only: node_id -> age of its last reading, for the quality tooltip. */
  ageByNode?: ReadonlyMap<string, number | null>;
}

const truth = (n: NodeState | undefined): number => n?.truth ?? n?.value ?? 0;

export function Equipment({ nodes, topo, ageByNode }: Props) {
  const get = (id: string) => nodes.get(id);
  const lit101 = get("LIT101");
  const lit301 = get("LIT301");
  const mv = get("MV101");
  const p101 = get("P101");
  const p301 = get("P301");
  return (
    <g>
      {lit101 && (
        <Tank
          label="T1"
          {...TANKS.T1}
          level={truth(lit101)}
          reported={lit101.value}
          status={lit101.status}
        />
      )}
      {lit301 && (
        <Tank
          label="T2"
          {...TANKS.T2}
          level={truth(lit301)}
          reported={lit301.value}
          status={lit301.status}
        />
      )}
      <g filter="url(#equip-shadow)">
        <rect
          x={FILTER.x}
          y={FILTER.y}
          width={FILTER.w}
          height={FILTER.h}
          rx={8}
          fill="var(--bg-0)"
          stroke="var(--text-2)"
          strokeOpacity={0.6}
          strokeWidth={2}
        />
        <rect
          x={FILTER.x + 2}
          y={FILTER.y + 2}
          width={FILTER.w - 4}
          height={FILTER.h - 4}
          rx={6}
          fill="url(#filter-hatch)"
        />
      </g>
      <text x={FILTER.x + 8} y={FILTER.y + FILTER.h - 8} className="fill-ink-1 font-mono" fontSize={TEXT}>
        Filter
      </text>
      {mv && <Valve at={ANCHOR.MV101} open={truth(mv)} status={mv.status} />}
      {p101 && <Pump at={ANCHOR.P101} speed={truth(p101)} status={p101.status} />}
      {p301 && <Pump at={ANCHOR.P301} speed={truth(p301)} status={p301.status} />}
      {[...nodes.values()].map((n) => {
        const a = anchorOf(n.id);
        if (!a) return null;
        const below = n.id === "MV101" || n.id === "P101" || n.id === "P301";
        const at = below ? { x: a.x, y: a.y + (n.id === "MV101" ? 44 : 56) } : a;
        return (
          <NodeBadge
            key={n.id}
            node={n}
            at={at}
            topo={topo.get(n.id)}
            ageMs={ageByNode?.get(n.id)}
          />
        );
      })}
    </g>
  );
}
