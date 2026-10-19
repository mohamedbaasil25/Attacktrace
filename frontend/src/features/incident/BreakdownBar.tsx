import type { OriginCandidate } from "../../lib/types";

const SEGMENTS = [
  { key: "deviation", color: "var(--origin)" },
  { key: "onset", color: "var(--affected)" },
  { key: "causal", color: "var(--accent)" },
] as const;

const f2 = (x: number): string => x.toFixed(2);

/** What the three signals contributed to a candidate's own score: a 3-segment stacked bar, with
 *  the numbers in a tooltip and in the accessible label (never colour alone). */
export function BreakdownBar({ c }: { c: OriginCandidate }) {
  const b = c.breakdown;
  if (!b) return null;
  const w = c.weights;
  const label = SEGMENTS.map((s) => `${s.key} ${f2(b[s.key])}`).join(", ");
  return (
    <div
      role="img"
      aria-label={`${c.id} score breakdown: ${label}`}
      className="flex h-2 w-full overflow-hidden rounded-sm bg-line-1"
      data-testid={`breakdown-${c.id}`}
    >
      {SEGMENTS.map((s) => (
        <div
          key={s.key}
          title={`${s.key} ${f2(b[s.key])}${w ? ` (weight ${f2(w[s.key])})` : ""}`}
          style={{
            width: `${Math.max(0, Math.min(1, b[s.key])) * 100}%`,
            background: s.color,
            borderRight: "1px solid var(--bg-1)",
            transition: "width var(--motion-slow) linear",
          }}
        />
      ))}
    </div>
  );
}

/** One legend line for the bars: swatch + name, so colour is never the only cue. */
export function BreakdownLegend() {
  return (
    <div className="flex gap-3 text-xs text-ink-2" aria-hidden>
      {SEGMENTS.map((s) => (
        <span key={s.key} className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />
          {s.key}
        </span>
      ))}
    </div>
  );
}
