import { clamp01 } from "../../lib/format";
import type { NodeStatus } from "../../lib/types";
import { HoverLabel } from "./HoverLabel";
import { TEXT, spinDuration, type Pt } from "./geometry";
import { STATUS_COLOR } from "./status";

interface TankProps {
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Physical level, %. */
  level: number;
  /** Level as reported to SCADA, %; drawn as a tick so spoofing is visible. */
  reported: number;
  status: NodeStatus;
}

const SPOOF_THRESHOLD_PCT = 3; // matches lib/format.ts's isSpoofed: >3% of a sensor's range

export function Tank({ label, x, y, w, h, level, reported, status }: TankProps) {
  // Phase 15 §4.2: the fill shows what SCADA believes (reported) -- the signature "spoofing
  // visible" moment is that the big, obvious fill can be WRONG. The thin ghost tick reveals the
  // physical truth underneath it.
  const fillH = (clamp01(reported / 100) * h) | 0;
  const extreme = reported >= 90 || reported <= 10;
  const truthY = y + h - clamp01(level / 100) * h;
  const delta = reported - level;
  const spoofed = Math.abs(delta) > SPOOF_THRESHOLD_PCT;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={6}
        fill="var(--bg-0)"
        stroke={status === "normal" ? "var(--line-2)" : STATUS_COLOR[status]}
        strokeWidth={status === "normal" ? 2 : 2.5}
      />
      <rect
        x={x + 2}
        y={y + h - fillH}
        width={w - 4}
        height={fillH}
        rx={4}
        fill={extreme ? "var(--affected)" : "var(--accent)"}
        fillOpacity={0.4}
        style={{ transition: "all 500ms linear" }}
      />
      {/* Ghost marker: the physical truth, always drawn thin so it reads as "underneath". */}
      <HoverLabel at={{ x: x - 6, y: truthY - TEXT - 8 }} text={`${label} physical truth ${level.toFixed(1)}%`}>
        <line
          x1={x - 6}
          x2={x + w + 6}
          y1={truthY}
          y2={truthY}
          stroke="var(--text-3)"
          strokeWidth={1.5}
          strokeDasharray="2 3"
          opacity={0.85}
          style={{ transition: "all 500ms linear" }}
        />
      </HoverLabel>
      {spoofed && (
        <g>
          <line
            x1={x + w + 6}
            x2={x + w + 6}
            y1={truthY}
            y2={y + h - fillH}
            stroke="var(--origin)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
          <g transform={`translate(${x + w + 8}, ${(truthY + (y + h - fillH)) / 2})`}>
            <rect x={0} y={-7} width={30} height={14} rx={3} fill="var(--origin)" fillOpacity={0.15} stroke="var(--origin)" strokeWidth={1} />
            <text x={15} y={4} textAnchor="middle" className="fill-origin font-mono" fontSize={10}>
              {`Δ${Math.abs(delta).toFixed(0)}`}
            </text>
          </g>
        </g>
      )}
      <text x={x + 8} y={y + 20} className="fill-muted font-mono" fontSize={TEXT}>
        {label}
      </text>
    </g>
  );
}

interface PumpProps {
  at: Pt;
  /** Physical speed 0..1. */
  speed: number;
  status: NodeStatus;
}

export function Pump({ at, speed, status }: PumpProps) {
  const dur = spinDuration(speed);
  return (
    <g>
      <circle cx={at.x} cy={at.y} r={26} fill="var(--bg-0)" stroke={STATUS_COLOR[status]} strokeWidth={status === "normal" ? 1 : 2} />
      <g
        className={dur === null ? "" : "spin"}
        style={{ transformOrigin: `${at.x}px ${at.y}px`, animationDuration: dur === null ? undefined : `${dur}s` }}
      >
        {[0, 120, 240].map((a) => (
          <path
            key={a}
            d={`M${at.x} ${at.y} L${at.x} ${at.y - 18}`}
            stroke="var(--text-2)"
            strokeWidth={4}
            strokeLinecap="round"
            transform={`rotate(${a} ${at.x} ${at.y})`}
          />
        ))}
      </g>
      <circle cx={at.x} cy={at.y} r={4} fill="var(--text-2)" />
    </g>
  );
}

interface ValveProps {
  at: Pt;
  /** Physical opening 0..1. */
  open: number;
  status: NodeStatus;
}

export function Valve({ at, open, status }: ValveProps) {
  const { x, y } = at;
  return (
    <g>
      <polygon
        points={`${x - 16},${y - 14} ${x + 16},${y + 14} ${x + 16},${y - 14} ${x - 16},${y + 14}`}
        fill="var(--accent)"
        fillOpacity={0.15 + 0.6 * clamp01(open)}
        stroke={STATUS_COLOR[status]}
        strokeWidth={status === "normal" ? 1 : 2}
        style={{ transition: "fill-opacity 500ms linear" }}
      />
    </g>
  );
}
