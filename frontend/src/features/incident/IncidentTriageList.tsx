import { Chip } from "../../components/ui/Chip";
import { STATUS_CHIP, elapsed, statusIcon } from "../../lib/incident";
import type { Incident } from "../../lib/types";

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** More than one incident is open: one compact row per incident (same chip vocabulary as the
 *  single-incident header), severity-sorted by the backend (docs/UI_SPEC.md §7). Clicking a
 *  row opens today's unchanged single-incident `Details` view for that incident. */
export function IncidentTriageList({
  incidents,
  now,
  onSelect,
}: {
  incidents: Incident[];
  now: number;
  onSelect: (id: string) => void;
}) {
  return (
    <div data-testid="incident-triage-list" className="flex flex-col divide-y divide-line-1">
      {incidents.map((inc) => {
        const sc = STATUS_CHIP[inc.status];
        const Icon = statusIcon(inc);
        const top = inc.origin[0];
        return (
          <button
            key={inc.id}
            type="button"
            data-testid="incident-triage-row"
            onClick={() => onSelect(inc.id)}
            className="flex items-center gap-1.5 p-2 text-left text-xs transition-colors duration-fast ease-out hover:bg-surface-2"
          >
            <Chip
              tone={inc.ambiguous ? "suspect" : sc.tone}
              icon={<Icon size={11} className={!inc.ambiguous && sc.spin ? "animate-spin" : ""} aria-hidden />}
            >
              {inc.ambiguous ? "Ambiguous" : sc.label}
            </Chip>
            <span className="font-mono text-ink-1">{top?.id ?? "–"}</span>
            {top && <span className="font-mono text-ink-3">{pct(top.confidence)}</span>}
            <span className="ml-auto font-mono text-ink-3">{elapsed(inc.detected_at, now)}</span>
          </button>
        );
      })}
    </div>
  );
}
