import { isActive } from "../../lib/incident";
import type { Incident, NodeState } from "../../lib/types";
import { LINKS, flowDuration, flowRatio, pulseDelay } from "./geometry";

interface Props {
  nodes: ReadonlyMap<string, NodeState>;
  incident: Incident | null;
}

/** Pipes with flowing dashes, control wires, and attack pulses along the incident path. */
export function Links({ nodes, incident }: Props) {
  const active = isActive(incident);
  return (
    <g>
      {LINKS.map((l) => {
        const dur = l.kind === "pipe" ? flowDuration(flowRatio(l, nodes)) : null;
        const delay = active ? pulseDelay(l, incident.path_edges, incident.path) : null;
        return (
          <g key={l.id}>
            {l.kind === "pipe" ? (
              <>
                <path d={l.d} stroke="var(--line-1)" strokeWidth={9} fill="none" strokeLinecap="butt" />
                <path
                  d={l.d}
                  className={dur === null ? "" : "flow"}
                  stroke="var(--accent)"
                  strokeOpacity={dur === null ? 0.12 : 0.9}
                  strokeWidth={3}
                  strokeDasharray="3 9"
                  fill="none"
                  style={dur === null ? undefined : { animationDuration: `${dur}s` }}
                />
              </>
            ) : (
              <path
                d={l.d}
                stroke="var(--text-2)"
                strokeOpacity={0.5}
                strokeWidth={1}
                strokeDasharray="4 4"
                fill="none"
              />
            )}
            {delay !== null && (
              <path
                d={l.d}
                pathLength={1}
                className="attack-pulse"
                stroke="var(--origin)"
                strokeWidth={4}
                strokeLinecap="round"
                fill="none"
                style={{ animationDelay: `${Math.min(delay, 6)}s` }}
              />
            )}
          </g>
        );
      })}
    </g>
  );
}
