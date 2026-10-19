import type { NodeStatus } from "../../lib/types";
import { STATUS_COLOR } from "./status";

/** Shape + colour, never colour alone (Phase 15 §3.1/§4.2):
 *  normal = filled circle with a check · suspect = triangle (pulses slowly) ·
 *  affected = diamond · origin = ring with a crosshair, plus an expanding double pulse. */
export function StatusGlyph({ status, cx, cy }: { status: NodeStatus; cx: number; cy: number }) {
  const fill = STATUS_COLOR[status];
  switch (status) {
    case "normal":
      return (
        <g aria-hidden>
          <circle cx={cx} cy={cy} r={4.5} fill={fill} />
          <path
            d={`M${cx - 2} ${cy}l1.3 1.4L${cx + 2.2} ${cy - 2}`}
            stroke="var(--bg-0)"
            strokeWidth={1}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </g>
      );
    case "suspect":
      return (
        <polygon
          className="status-suspect-pulse"
          points={`${cx},${cy - 5} ${cx + 5},${cy + 4} ${cx - 5},${cy + 4}`}
          fill={fill}
        />
      );
    case "affected":
      return (
        <polygon
          points={`${cx},${cy - 6} ${cx + 6},${cy} ${cx},${cy + 6} ${cx - 6},${cy}`}
          fill={fill}
        />
      );
    case "origin":
      return (
        <g aria-hidden>
          <circle
            className="status-origin-pulse"
            cx={cx}
            cy={cy}
            r={6}
            fill="none"
            stroke={fill}
            strokeWidth={1.5}
          />
          <circle
            className="status-origin-pulse"
            style={{ animationDelay: "0.8s" }}
            cx={cx}
            cy={cy}
            r={6}
            fill="none"
            stroke={fill}
            strokeWidth={1.5}
          />
          <circle cx={cx} cy={cy} r={5} fill="none" stroke={fill} strokeWidth={1.5} />
          <path d={`M${cx - 5} ${cy}h10M${cx} ${cy - 5}v10`} stroke={fill} strokeWidth={1} />
        </g>
      );
  }
}
