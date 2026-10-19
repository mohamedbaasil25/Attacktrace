import type { Incident } from "../../lib/types";

export function PathChips({ incident }: { incident: Incident }) {
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
