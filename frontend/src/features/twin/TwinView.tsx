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
    <div className="relative h-full w-full">
      <svg
        viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        role="img"
        aria-label="Plant digital twin"
      >
        <defs>
          {/* Phase 15 §4.2: a subtle 24px dot grid under the P&ID -- instrument-panel texture.
              `line-2` + an explicit fade (not `line-1` at full strength): `line-1` is tuned to sit
              barely above the dark theme's near-black canvas, which put it essentially AT the
              light theme's near-white canvas -- invisible, not subtle. `line-2` has enough of its
              own contrast in both themes; the opacity brings it back down to "texture," not
              "grid," in either. */}
          <pattern id="twin-dot-grid" width={24} height={24} patternUnits="userSpaceOnUse">
            <circle cx={1} cy={1} r={1} fill="var(--line-2)" fillOpacity={0.6} />
          </pattern>
          <pattern id="filter-hatch" width={8} height={8} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1={0} y1={0} x2={0} y2={8} stroke="var(--text-2)" strokeOpacity={0.25} strokeWidth={2} />
          </pattern>
          <linearGradient id="tank-liquid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.55} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.22} />
          </linearGradient>
          <linearGradient id="tank-liquid-warn" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--affected)" stopOpacity={0.55} />
            <stop offset="100%" stopColor="var(--affected)" stopOpacity={0.22} />
          </linearGradient>
          <radialGradient id="pump-casing" cx="35%" cy="30%" r="75%">
            <stop offset="0%" stopColor="var(--bg-2)" />
            <stop offset="100%" stopColor="var(--bg-0)" />
          </radialGradient>
          <linearGradient id="badge-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--bg-2)" />
            <stop offset="100%" stopColor="var(--bg-1)" />
          </linearGradient>
          <filter id="equip-shadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodColor="#000" floodOpacity="0.35" />
          </filter>
          <filter id="pipe-glow" x="-40%" y="-200%" width="180%" height="500%">
            <feGaussianBlur stdDeviation="1.6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
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
      <span className="pointer-events-none absolute bottom-1.5 left-2 font-mono text-[10px] uppercase tracking-[0.04em] text-ink-3">
        Equipment and process flow · hover a tag for detail
      </span>
    </div>
  );
}
