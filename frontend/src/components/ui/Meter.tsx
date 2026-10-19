/** A single-value horizontal meter (0-1 fraction): impact countdowns, stress gauges. For a
 *  multi-segment bar (the origin confidence breakdown), compose multiple Meters or use the
 *  existing BreakdownBar, which owns that specific layout. */
export function Meter({
  value,
  tone = "accent",
  label,
}: {
  value: number;
  tone?: "accent" | "normal" | "suspect" | "affected" | "origin";
  label?: string;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const fill: Record<string, string> = {
    accent: "bg-accent",
    normal: "bg-normal",
    suspect: "bg-suspect",
    affected: "bg-affected",
    origin: "bg-origin",
  };
  return (
    <div
      role="meter"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-1.5 w-full overflow-hidden rounded-sm bg-surface-3"
    >
      <div
        className={`h-full ${fill[tone]} transition-[width] duration-base ease-out`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
