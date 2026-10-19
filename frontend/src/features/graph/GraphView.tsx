import { Background, MarkerType, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { resolveSelected } from "../../lib/incident";
import { selectView, useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { edgeDelay, edgeId, layoutEdges, visibleEdges } from "./edges";
import { groupLayout, layerLayout } from "./layout";
import {
  PlantNodeView,
  PulseEdgeView,
  type PlantNode,
  type PulseEdgeT,
} from "./GraphParts";

const nodeTypes = { plant: PlantNodeView };
const edgeTypes = { pulse: PulseEdgeView };

/** Process graph, left to right. Edges on the incident path glow and a pulse travels along
 *  them in onset order; learned causal edges are dashed. */
export function GraphView() {
  const topology = useLive((s) => s.topology);
  const view = useLive(selectView);
  const liveHealth = useLive((s) => s.liveHealth);
  const selectedIncidentId = useUi((s) => s.selectedIncidentId);

  const positions = useMemo(
    () =>
      topology
        ? topology.edges.some((e) => e.kind === "static")
          ? layerLayout(
              topology.nodes.map((n) => n.id),
              layoutEdges(topology.edges),
            )
          : groupLayout(topology.nodes.map((n) => n.id)) // no P&ID: one block per process
        : {},
    [topology],
  );

  const nodes = useMemo<PlantNode[]>(() => {
    const byId = new Map((view?.nodes ?? []).map((n) => [n.id, n]));
    const ageById = new Map((liveHealth ?? []).map((h) => [h.node_id, h.age_ms]));
    return (topology?.nodes ?? []).map((t) => {
      const live = byId.get(t.id);
      return {
        id: t.id,
        type: "plant",
        position: positions[t.id] ?? { x: 0, y: 0 },
        data: {
          id: t.id,
          kind: t.type,
          value: live?.value ?? null,
          status: live?.status ?? "normal",
          quality: live?.quality,
          ageMs: ageById.get(t.id),
        },
        draggable: false,
        selectable: false,
      };
    });
  }, [topology, view, positions, liveHealth]);

  const incident = resolveSelected(view?.incidents ?? [], selectedIncidentId);
  const edges = useMemo<PulseEdgeT[]>(
    () =>
      visibleEdges(topology?.edges ?? []).map((e) => {
        const delay = edgeDelay(e.src, e.dst, incident);
        return {
          id: edgeId(e),
          source: e.src,
          target: e.dst,
          type: "pulse",
          data: { learned: e.kind === "learned", delay },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color: delay === null ? "var(--text-2)" : "var(--origin)",
          },
          selectable: false,
        };
      }),
    [topology, incident],
  );

  return (
    <div className="h-full w-full" aria-label="Process graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode="dark"
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.3}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
      >
        <Background color="var(--line-1)" gap={24} />
      </ReactFlow>
    </div>
  );
}
