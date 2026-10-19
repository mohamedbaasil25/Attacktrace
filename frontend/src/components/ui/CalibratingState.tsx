import { ProgressRing } from "./ProgressRing";

/** LIVE is recording clean traffic and training its detector: progress ring + label, nothing
 *  else — there is no incident data worth drawing yet. */
export function CalibratingState({ progress }: { progress: number | null }) {
  const pct = progress === null ? null : Math.round(Math.max(0, Math.min(1, progress)) * 100);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-ink-2">
      <ProgressRing progress={progress} />
      <span role="status" className="font-mono text-xs">
        Calibrating{pct !== null ? ` ${pct}%` : ""}
      </span>
    </div>
  );
}
