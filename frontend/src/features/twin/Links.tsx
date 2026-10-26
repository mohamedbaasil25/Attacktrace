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
                {/* `line-2`, not `line-1`: the casing needs to read as a pipe against the canvas
                    in both themes -- `line-1` (border-weight, barely off the page background by
                    design) all but disappeared against the light theme's near-white canvas. */}
                <path d={l.d} stroke="var(--line-2)" strokeWidth={10} fill="none" strokeLinecap="round" />
                <path d={l.d} stroke="var(--bg-0)" strokeOpacity={0.35} strokeWidth={6} fill="none" strokeLinecap="round" />
                <path
                  d={l.d}
                  className={dur === null ? "" : "flow"}
                  stroke="var(--accent)"
                  strokeOpacity={dur === null ? 0.12 : 0.95}
                  strokeWidth={3}
                  strokeDasharray="3 9"
                  strokeLinecap="round"
                  fill="none"
                  filter={dur === null ? undefined : "url(#pipe-glow)"}
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
