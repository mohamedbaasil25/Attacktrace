import type { MagnitudeInput } from "../../lib/scenarios";

interface Props {
  input: MagnitudeInput;
  value: number;
  onChange: (v: number) => void;
  className: string;
}

export function MagnitudeField({ input, value, onChange, className }: Props) {
  if (input.kind === "none") {
    return (
      <div className="flex flex-col gap-1 text-xs text-ink-2">
        Magnitude
        <span className={`${className} flex items-center opacity-50`}>–</span>
      </div>
    );
  }
  if (input.kind === "toggle") {
    return (
      <div className="flex flex-col gap-1 text-xs text-ink-3">
        Command
        <div role="group" aria-label="Command" className="inline-flex rounded-md border border-line-1 p-px">
          {([0, 1] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={value === v}
              onClick={() => onChange(v)}
              className={`h-8 flex-1 rounded-sm font-mono text-xs transition-colors duration-fast ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
                value === v ? "bg-accent text-surface-0" : "text-ink-3 hover:text-ink-1"
              }`}
            >
              {v === 1 ? input.on : input.off}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1 text-xs text-ink-2">
      <div className="flex items-center justify-between">
        <span>Magnitude</span>
        <span className="font-mono text-ink-1">
          {value}
          {input.unit}
        </span>
      </div>
      <input
        type="range"
        aria-label={`Magnitude${input.unit ? ` (${input.unit})` : ""}`}
        className="h-1.5 w-full accent-accent"
        value={value}
        step={input.step}
        min={input.min}
        max={input.max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <input
        type="number"
        aria-label={`Magnitude value${input.unit ? ` in ${input.unit}` : ""}`}
        className={className}
        value={value}
        step={input.step}
        min={input.min}
        max={input.max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
