import { History, Pause, Play, Radio, RotateCcw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { incidentStartIndex } from "../../lib/replay";
import { useLive } from "../../store/live";

function Btn({
  icon: Icon,
  label,
  onClick,
  pressed,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-8 w-8 items-center justify-center rounded-md border transition-colors duration-fast ease-out disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
        pressed ? "border-accent text-accent" : "border-line-1 text-ink-3 hover:text-ink-1"
      }`}
    >
      <Icon size={14} aria-hidden />
    </button>
  );
}

/** Replay incident, play, pause, back to live. */
export function ReplayControls() {
  const playing = useLive((s) => s.playing);
  const cursor = useLive((s) => s.cursor);
  const hasIncident = useLive((s) => incidentStartIndex(s.buffer) !== null);
  const { play, pause, goLive, replayIncident } = useLive.getState();
  const live = cursor === null;
  const running = live || playing; // the stream itself counts as playing
  return (
    <div className="flex flex-col items-start gap-1 p-2">
      <div className="flex gap-1">
        <Btn icon={RotateCcw} label="Replay incident" onClick={replayIncident} disabled={!hasIncident} />
        <Btn
          icon={running ? Pause : Play}
          label={running ? "Pause" : "Play"}
          onClick={running ? pause : play}
          pressed={playing}
        />
      </div>
      <button
        type="button"
        onClick={goLive}
        disabled={live}
        className={`flex h-8 items-center gap-1 rounded-full border px-2 font-mono text-xs transition-colors duration-fast ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
          live ? "border-normal text-normal" : "border-line-1 text-ink-3 hover:text-ink-1"
        }`}
      >
        {live ? <Radio size={12} aria-hidden /> : <History size={12} aria-hidden />}
        {live ? "Live" : "Replay"}
      </button>
    </div>
  );
}
