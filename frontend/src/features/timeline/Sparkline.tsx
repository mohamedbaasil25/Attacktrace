import { formatValue } from "../../lib/format";
import { seriesPath } from "../../lib/replay";
import { RING_CAPACITY } from "../../store/live";

/** Virtual drawing width; the SVG stretches to its container, so no measuring is needed. */
const VW = 1000;

interface Props {
  id: string;
  reported: readonly number[];
  truth: readonly number[];
  /** Sample index of the value shown in the label (cursor or newest). */
  at: number;
  height: number;
}

/** Reported value (solid) over physical truth (dashed); a gap between them is spoofing. */
export function Sparkline({ id, reported, truth, at, height }: Props) {
  const all = [...reported, ...truth];
  const min = all.length ? Math.min(...all) : 0;
  const max = all.length ? Math.max(...all) : 1;
  const pad = (max - min) * 0.1 || 0.5;
  const lo = min - pad;
  const hi = max + pad;
  const shown = reported[at];
  return (
    <div className="grid grid-cols-[148px_1fr] items-center" style={{ height }}>
      <div className="flex items-baseline gap-2 pl-2 font-mono leading-none">
        <span className="w-14 text-xs text-ink-3">{id}</span>
        <span className="whitespace-nowrap text-xs">
          {shown === undefined ? "–" : formatValue(id, shown)}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${VW} ${height}`}
        preserveAspectRatio="none"
        className="h-full w-full min-w-0"
        aria-hidden
      >
        <path
          d={seriesPath(truth, RING_CAPACITY, VW, height, lo, hi)}
          fill="none"
          stroke="var(--text-3)"
          strokeWidth={1}
          strokeDasharray="3 3"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={seriesPath(reported, RING_CAPACITY, VW, height, lo, hi)}
          fill="none"
          stroke="var(--text-1)"
          strokeWidth={1.2}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}
