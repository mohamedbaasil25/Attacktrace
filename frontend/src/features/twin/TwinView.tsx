import { useMemo } from "react";
import { resolveSelected } from "../../lib/incident";
import { nodeMap, selectView, useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { Equipment } from "./EquipmentLayer";
import { Links } from "./Links";
import { VIEW, anchorOf } from "./geometry";

/** Pure-SVG plant: tanks fill with the physical level, pipes flow, pumps spin. */
export function TwinView() {
  const latest = useLive(selectView);
  const topology = useLive((s) => s.topology);
  const liveHealth = useLive((s) => s.liveHealth);
  const focusedNode = useUi((s) => s.focusedNode);
  const selectedIncidentId = useUi((s) => s.selectedIncidentId);
  const incident = latest ? resolveSelected(latest.incidents, selectedIncidentId) : null;
  const focusAt = focusedNode ? anchorOf(focusedNode) : undefined;
  const nodes = useMemo(() => new Map((latest?.nodes ?? []).map((n) => [n.id, n])), [latest]);
  const topo = useMemo(() => nodeMap(topology), [topology]);
  const ageByNode = useMemo(
    () => new Map((liveHealth ?? []).map((h) => [h.node_id, h.age_ms])),
    [liveHealth],
  );
  if (!latest) return null;
  return (
    <svg
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      preserveAspectRatio="xMidYMid meet"
      className="h-full w-full"
      role="img"
      aria-label="Plant digital twin"
    >
      <defs>
        {/* Phase 15 §4.2: a subtle 24px dot grid under the P&ID -- instrument-panel texture. */}
        <pattern id="twin-dot-grid" width={24} height={24} patternUnits="userSpaceOnUse">
          <circle cx={1} cy={1} r={1} fill="var(--line-1)" />
        </pattern>
      </defs>
      <rect x={0} y={0} width={VIEW.w} height={VIEW.h} fill="url(#twin-dot-grid)" />
      <Links nodes={nodes} incident={incident} />
      <Equipment nodes={nodes} topo={topo} ageByNode={ageByNode} />
      {focusAt && (
        <circle
          cx={focusAt.x}
          cy={focusAt.y}
          r={26}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={2}
          strokeDasharray="3 3"
          opacity={0.8}
        />
      )}
    </svg>
  );
}
