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
  const topY = y + h - fillH;
  const gradientId = extreme ? "tank-liquid-warn" : "tank-liquid";
  // A gentle wave on the liquid's top edge -- purely decorative (height still tracks `reported`
  // exactly), four control points across the tank width.
  const wave = `M${x + 2} ${topY} C${x + w * 0.28} ${topY - 4}, ${x + w * 0.4} ${topY + 4}, ${x + w * 0.5} ${topY} S${x + w * 0.86} ${topY - 4}, ${x + w - 2} ${topY} V${y + h - 2} H${x + 2} Z`;
  return (
    <g filter="url(#equip-shadow)">
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        fill="var(--bg-0)"
        stroke={status === "normal" ? "var(--line-2)" : STATUS_COLOR[status]}
        strokeWidth={status === "normal" ? 2 : 2.5}
      />
      {/* Glass sheen: a soft vertical highlight down the left third, purely decorative. */}
      <rect x={x + 6} y={y + 6} width={w * 0.22} height={h - 12} rx={8} fill="var(--text-1)" opacity={0.035} />
      <path d={wave} fill={`url(#${gradientId})`} style={{ transition: "all 500ms linear" }} />
      {/* Level ticks at 25/50/75%, purely decorative scale markers. `text-3` (not the
          border-weight `line-2`) for the tick line too, and no extra group-level fade on top of
          it: `line-2` at 0.5 opacity reads fine on the dark theme's near-black canvas but is
          close to invisible on the light theme's near-white one -- `text-3` carries enough of
          its own contrast in both to not need compounding. */}
      {[0.25, 0.5, 0.75].map((f) => {
        const ty = y + h - f * h;
        return (
          <g key={f}>
            <line
              x1={x + w - 14}
              x2={x + w - 4}
              y1={ty}
              y2={ty}
              stroke="var(--text-3)"
              strokeWidth={1}
              opacity={0.75}
            />
            <text
              x={x + w - 18}
              y={ty + 3}
              textAnchor="end"
              className="fill-ink-3 font-mono"
              fontSize={9}
              opacity={0.95}
            >
              {f * 100}
            </text>
          </g>
        );
      })}
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
      {/* Header chip overlapping the shell's top edge, instead of plain inset text. */}
      <g transform={`translate(${x + w / 2}, ${y})`}>
        <rect x={-22} y={-11} width={44} height={20} rx={5} fill="var(--bg-2)" stroke="var(--line-2)" strokeWidth={1} />
        <text x={0} y={3} textAnchor="middle" className="fill-ink-1 font-mono font-medium" fontSize={TEXT * 0.72}>
          {label}
        </text>
      </g>
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
    <g filter="url(#equip-shadow)">
      <circle cx={at.x} cy={at.y} r={28} fill="url(#pump-casing)" stroke={STATUS_COLOR[status]} strokeWidth={status === "normal" ? 1.5 : 2.5} />
      <circle cx={at.x} cy={at.y} r={22} fill="none" stroke="var(--line-2)" strokeWidth={1} opacity={0.6} />
      <g
        className={dur === null ? "" : "spin"}
        style={{ transformOrigin: `${at.x}px ${at.y}px`, animationDuration: dur === null ? undefined : `${dur}s` }}
      >
        {[0, 120, 240].map((a) => (
          <path
            key={a}
            d={`M${at.x} ${at.y} L${at.x - 6} ${at.y - 17} Q${at.x} ${at.y - 20} ${at.x + 6} ${at.y - 17} Z`}
            fill="var(--text-1)"
            opacity={0.85}
            transform={`rotate(${a} ${at.x} ${at.y})`}
          />
        ))}
      </g>
      <circle cx={at.x} cy={at.y} r={5} fill="var(--text-1)" />
      <circle cx={at.x} cy={at.y} r={2} fill="var(--bg-0)" />
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
    <g filter="url(#equip-shadow)">
      <rect x={x - 22} y={y - 18} width={44} height={36} rx={8} fill="var(--bg-0)" stroke="var(--line-2)" strokeWidth={1} opacity={0.9} />
      <polygon
        points={`${x - 14},${y - 12} ${x + 14},${y + 12} ${x + 14},${y - 12} ${x - 14},${y + 12}`}
        fill="var(--accent)"
        fillOpacity={0.2 + 0.65 * clamp01(open)}
        stroke={STATUS_COLOR[status]}
        strokeWidth={status === "normal" ? 1 : 2}
        style={{ transition: "fill-opacity 500ms linear" }}
      />
      <circle cx={x} cy={y} r={2.5} fill="var(--text-1)" />
    </g>
  );
}
