import { AlertOctagon, Zap } from "lucide-react";
import { etaUrgency, formatEta } from "../../lib/format";
import type { Impact } from "../../lib/types";

function tone(u: number): string {
  if (u > 0.66) return "var(--origin)";
  if (u > 0.33) return "var(--affected)";
  return u > 0 ? "var(--suspect)" : "var(--normal)";
}

function Meter({ label, value, text }: { label: string; value: number; text: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr_48px] items-center gap-2 text-xs">
      <span className="text-ink-2">{label}</span>
      <div className="h-1 overflow-hidden rounded-full bg-line-1" aria-hidden>
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.max(value, 0.04) * 100}%`,
            background: tone(value),
            transition: "width var(--motion-slow) linear",
          }}
        />
      </div>
      <span className="text-right font-mono" style={{ color: value > 0.33 ? tone(value) : undefined }}>
        {text}
      </span>
    </div>
  );
}

export function ImpactMeters({ impact }: { impact: Impact | null }) {
  if (!impact) return null;
  const stress = impact.pump_stress;
  return (
    <div className="flex flex-col gap-1">
      <Meter label="T1 overflow" value={etaUrgency(impact.t1_overflow_s)} text={formatEta(impact.t1_overflow_s)} />
      <Meter label="T1 dry-run" value={etaUrgency(impact.t1_dry_s)} text={formatEta(impact.t1_dry_s)} />
      <Meter label="T2 overflow" value={etaUrgency(impact.t2_overflow_s)} text={formatEta(impact.t2_overflow_s)} />
      <Meter label="T2 dry-run" value={etaUrgency(impact.t2_dry_s)} text={formatEta(impact.t2_dry_s)} />
      {(["P101", "P301"] as const).map((p) => (
        <Meter key={p} label={`${p} stress`} value={stress[p] ?? 0} text={`${Math.round((stress[p] ?? 0) * 100)}%`} />
      ))}
      <div className="mt-1 flex items-center gap-1 text-xs text-ink-2">
        <Zap size={12} aria-hidden />
        <span>Energy wasted</span>
        <span className="ml-auto font-mono text-ink-1">{impact.energy_wasted_kwh.toFixed(3)} kWh</span>
      </div>
      {(impact.t1_overflow_s !== null || impact.t2_overflow_s !== null) && (
        <div className="flex items-center gap-1 text-xs text-origin">
          <AlertOctagon size={12} aria-hidden />
          <span>Overflow risk</span>
        </div>
      )}
    </div>
  );
}
