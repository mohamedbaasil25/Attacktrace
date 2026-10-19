import { History as HistoryIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../../components/ui/EmptyState";
import { ApiError, getHistory } from "../../lib/api";
import { formatValue } from "../../lib/format";
import { HISTORY_RANGES, historyPath } from "../../lib/history";
import type { HistorySample } from "../../lib/types";

const VW = 1000;
const VH = 120;

/** The real retained history for one node (Production Transition Roadmap §3), beyond the
 *  engine's own 5-minute in-memory ring buffer the Timeline's Sparklines read from. Fetched on
 *  demand, not pushed over the WS -- this is a deliberately separate, slower-moving view. */
export function HistoryTrend({ nodeIds }: { nodeIds: string[] }) {
  const [node, setNode] = useState(nodeIds[0] ?? "");
  const [rangeS, setRangeS] = useState<number>(HISTORY_RANGES[0].seconds);
  const [samples, setSamples] = useState<HistorySample[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!node) return;
    let live = true;
    setSamples(null);
    setError(null);
    getHistory(node, Date.now() / 1000 - rangeS)
      .then((s) => live && setSamples(s))
      .catch((e: unknown) => {
        if (!live) return;
        setError(e instanceof ApiError ? e.message : "Could not load history");
        setSamples([]);
      });
    return () => {
      live = false;
    };
  }, [node, rangeS]);

  const path = useMemo(() => (samples ? historyPath(samples, VW, VH) : ""), [samples]);
  const latest = samples?.[samples.length - 1];
  const oldest = samples?.[0];

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <div className="flex items-center gap-2 text-xs">
        <select
          aria-label="History node"
          value={node}
          onChange={(e) => setNode(e.target.value)}
          className="h-7 rounded-sm border border-line-1 bg-surface-0 px-1.5 font-mono text-ink-1"
        >
          {nodeIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <div role="group" aria-label="History range" className="flex gap-1">
          {HISTORY_RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              aria-pressed={rangeS === r.seconds}
              onClick={() => setRangeS(r.seconds)}
              className={`h-7 rounded-sm border px-2 font-mono text-xs transition-colors duration-fast ease-out ${
                rangeS === r.seconds
                  ? "border-accent text-accent"
                  : "border-line-1 text-ink-2 hover:text-ink-1"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        {latest && (
          <span className="ml-auto font-mono text-ink-1">{formatValue(node, latest.value)}</span>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        {samples === null ? (
          <EmptyState icon={HistoryIcon} text="Loading" />
        ) : samples.length < 2 ? (
          <EmptyState icon={HistoryIcon} text={error ?? "No history yet"} />
        ) : (
          <svg viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none" className="h-full w-full">
            <path
              d={path}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}
      </div>
      {oldest && latest && samples && samples.length >= 2 && (
        <div className="flex justify-between font-mono text-caption text-ink-3">
          <span>{new Date(oldest.t * 1000).toLocaleTimeString()}</span>
          <span>{samples.length} samples</span>
          <span>{new Date(latest.t * 1000).toLocaleTimeString()}</span>
        </div>
      )}
    </div>
  );
}
