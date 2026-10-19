import type { ReactNode } from "react";

/** A circular progress/value ring: `value` 0..1 fills clockwise from the top; `null` shows a
 *  static partial arc (unknown progress). Used by `ProgressRing` (calibrating) and the origin
 *  card's confidence ring -- one drawing, two call sites. */
export function Ring({
  value,
  size = 72,
  strokeWidth = 6,
  tone = "accent",
  children,
}: {
  value: number | null;
  size?: number;
  strokeWidth?: number;
  tone?: "accent" | "normal" | "suspect" | "affected" | "origin";
  children?: ReactNode;
}) {
  const r = size / 2 - strokeWidth;
  const c = 2 * Math.PI * r;
  const v = value === null ? null : Math.max(0, Math.min(1, value));
  const stroke: Record<string, string> = {
    accent: "var(--accent)",
    normal: "var(--normal)",
    suspect: "var(--suspect)",
    affected: "var(--affected)",
    origin: "var(--origin)",
  };
  return (
    <span className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--line-1)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={stroke[tone]}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={v === null ? c * 0.75 : c * (1 - v)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset var(--motion-slow) linear" }}
        />
      </svg>
      {children && (
        <span className="absolute inset-0 flex items-center justify-center">{children}</span>
      )}
    </span>
  );
}
