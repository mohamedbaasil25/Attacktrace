import { ChevronRight } from "lucide-react";
import type { Incident } from "../../lib/types";

/** Vertical: a dotted timeline (fits the narrow incident column). Horizontal: a wrapping chip
 *  flow ("LIT101 +0.0s › PLC1 +0.0s › ...") for wider pages (e.g. Investigations). Same
 *  data (`incident.path`) either way -- this is presentation only. */
export function PathChips({
  incident,
  orientation = "vertical",
}: {
  incident: Incident;
  orientation?: "vertical" | "horizontal";
}) {
  if (orientation === "horizontal") {
    return (
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Attack path">
        {incident.path.map((s, i) => {
          const origin = i === 0;
          const last = i === incident.path.length - 1;
          return (
            <li key={s.id} className="flex items-center gap-1">
              <span
                className={`flex items-center gap-1.5 rounded-sm border px-2 py-1 font-mono text-caption ${
                  origin ? "border-origin/40 bg-origin/10 text-origin" : "border-line-1 text-ink-2"
                }`}
              >
                <span className={origin ? "font-semibold" : ""}>{s.id}</span>
                <span className="text-ink-3">+{s.t.toFixed(1)}s</span>
              </span>
              {!last && <ChevronRight size={14} className="shrink-0 text-ink-3" aria-hidden />}
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <ol className="flex flex-col" aria-label="Attack path">
      {incident.path.map((s, i) => {
        const origin = i === 0;
        const last = i === incident.path.length - 1;
        return (
          <li key={s.id} className="flex gap-2">
            <div className="flex flex-col items-center">
              <span
                className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                  origin ? "bg-origin ring-2 ring-origin/30" : "bg-ink-3"
                }`}
                aria-hidden
              />
              {!last && <span className="w-px flex-1 bg-line-1" aria-hidden />}
            </div>
            <div className={`flex items-center gap-1.5 pb-2 font-mono text-xs ${origin ? "text-origin" : "text-ink-2"}`}>
              <span className={origin ? "font-semibold" : ""}>{s.id}</span>
              <span className="text-ink-3">+{s.t.toFixed(1)}s</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
