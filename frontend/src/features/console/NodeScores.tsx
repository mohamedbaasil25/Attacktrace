import { Meter } from "../../components/ui/Meter";
import { selectView, useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { STATUS_LABEL } from "../twin/status";
import { StatusGlyph } from "../twin/StatusGlyph";

// Purely a compact visual cue -- the frontend has no per-node alert threshold, so the bar scales
// against a generous fixed ceiling rather than claiming calibrated meaning. The number stays
// authoritative.
const SCORE_CEILING = 3;

/** Live node scores (smoothed forecast error) with status, from the message already streamed.
 *  Clicking a row focuses that node on the twin. */
export function NodeScores() {
  const nodes = useLive((s) => selectView(s)?.nodes);
  const focusedNode = useUi((s) => s.focusedNode);
  const toggleFocusedNode = useUi((s) => s.toggleFocusedNode);
  if (!nodes?.length) return null;
  return (
    <div className="flex flex-col gap-1 border-t border-line-1 pt-2" aria-label="Node scores">
      <span className="text-xs text-ink-3">Node scores</span>
      {nodes.map((n) => {
        const focused = n.id === focusedNode;
        return (
          <button
            key={n.id}
            type="button"
            aria-pressed={focused}
            onClick={() => toggleFocusedNode(n.id)}
            title={STATUS_LABEL[n.status]}
            className={`flex items-center gap-2 rounded-sm px-1 py-0.5 font-mono text-xs transition-colors duration-fast ease-out ${
              focused ? "bg-accent-soft text-ink-1" : "text-ink-2 hover:bg-surface-2"
            }`}
          >
            <svg width={14} height={14} viewBox="-7 -7 14 14" aria-label={STATUS_LABEL[n.status]} role="img">
              <StatusGlyph status={n.status} cx={0} cy={0} />
            </svg>
            <span className="w-16 text-left">{n.id}</span>
            <Meter
              value={n.score / SCORE_CEILING}
              tone={n.status === "normal" ? "accent" : n.status}
              label={`${n.id} score ${n.score.toFixed(2)}`}
            />
            <span className="w-9 text-right text-ink-3">{n.score.toFixed(2)}</span>
          </button>
        );
      })}
    </div>
  );
}
