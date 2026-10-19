import type { HistorySample } from "./types";

/** An SVG path for retained historian samples: unlike the ring buffer's fixed-capacity index
 *  (`lib/replay.ts`'s `seriesPath`), these carry real, irregular timestamps, so x is placed by
 *  time within the samples' own span, not by position. Empty/single-sample input draws nothing. */
export function historyPath(samples: readonly HistorySample[], w: number, h: number): string {
  if (samples.length < 2) return "";
  const t0 = samples[0]?.t ?? 0;
  const t1 = samples[samples.length - 1]?.t ?? t0;
  const span = t1 - t0 || 1;
  const values = samples.map((s) => s.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.1 || 0.5;
  const lo = min - pad;
  const hi = max + pad;
  const vSpan = hi - lo || 1;
  return samples
    .map((s, i) => {
      const x = ((s.t - t0) / span) * w;
      const y = h - ((s.value - lo) / vSpan) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

/** Rounds a lookback window to a short, stable label ("1h", "6h", "24h", ...). */
export const HISTORY_RANGES = [
  { label: "1h", seconds: 3600 },
  { label: "6h", seconds: 6 * 3600 },
  { label: "24h", seconds: 24 * 3600 },
  { label: "7d", seconds: 7 * 24 * 3600 },
] as const;
