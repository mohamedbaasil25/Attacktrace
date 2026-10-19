import {
  BaseEdge,
  Handle,
  Position,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { formatValue } from "../../lib/format";
import { QUALITY_ICON, QUALITY_LABEL, ageLabel } from "../../lib/quality";
import type { NodeKind, NodeStatus, Quality } from "../../lib/types";
import { STATUS_COLOR, STATUS_LABEL } from "../twin/status";
import { StatusGlyph } from "../twin/StatusGlyph";

export interface PlantNodeData extends Record<string, unknown> {
  id: string;
  kind: NodeKind;
  value: number | null;
  status: NodeStatus;
  /** LIVE only. */
  quality?: Quality | null;
  ageMs?: number | null;
}
export type PlantNode = Node<PlantNodeData, "plant">;

export function PlantNodeView({ data }: NodeProps<PlantNode>) {
  const flagged = data.status !== "normal";
  const QualityIcon = data.quality && data.quality !== "good" ? QUALITY_ICON[data.quality] : undefined;
  return (
    <div
      title={`${data.id} · ${STATUS_LABEL[data.status]}`}
      className={`relative flex h-11 w-[104px] items-center rounded-lg bg-surface-2 px-2 ${
        data.status === "origin" ? "origin-halo" : ""
      }`}
      style={{
        border: `${flagged ? 2 : 1}px solid ${STATUS_COLOR[data.status]}`,
        transition: "border-color var(--motion-fast)",
      }}
    >
      <Handle type="target" position={Position.Left} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <div className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="font-mono text-xs text-ink-3">{data.id}</span>
        <span className="font-mono text-xs">
          {data.value === null ? "–" : formatValue(data.id, data.value)}
        </span>
      </div>
      {QualityIcon && data.quality && (
        <div
          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-surface-2 text-suspect"
          title={`${QUALITY_LABEL[data.quality]} · ${ageLabel(data.ageMs)}`}
        >
          <QualityIcon size={11} aria-hidden />
        </div>
      )}
      <svg width={14} height={14} viewBox="0 0 14 14" aria-hidden>
        <StatusGlyph status={data.status} cx={7} cy={7} />
      </svg>
      <Handle type="source" position={Position.Right} className="!h-1 !w-1 !border-0 !bg-transparent" />
    </div>
  );
}

export interface PulseEdgeData extends Record<string, unknown> {
  learned: boolean;
  /** Seconds before the attack pulse runs; null when the edge is off the incident path. */
  delay: number | null;
}
export type PulseEdgeT = Edge<PulseEdgeData, "pulse">;

export function PulseEdgeView(props: EdgeProps<PulseEdgeT>) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd } = props;
  const [d] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const onPath = data?.delay !== null && data?.delay !== undefined;
  return (
    <>
      <BaseEdge
        path={d}
        markerEnd={markerEnd}
        style={{
          stroke: onPath ? "var(--origin)" : "var(--text-2)",
          strokeOpacity: onPath ? 0.9 : data?.learned ? 0.25 : 0.55,
          strokeWidth: onPath ? 2 : 1,
          strokeDasharray: data?.learned ? "4 4" : undefined,
        }}
      />
      {onPath && (
        <path
          d={d}
          pathLength={1}
          className="attack-pulse"
          stroke="var(--origin)"
          strokeWidth={5}
          strokeLinecap="round"
          fill="none"
          style={{ animationDelay: `${Math.min(data.delay ?? 0, 6)}s` }}
        />
      )}
    </>
  );
}
