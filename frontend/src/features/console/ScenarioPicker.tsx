import { Snowflake, TrendingDown, TrendingUp, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Chip } from "../../components/ui/Chip";
import { Tooltip } from "../../components/ui/Tooltip";
import { SCENARIO_LABEL } from "../../lib/scenarios";
import type { Scenario } from "../../lib/types";

// MITRE ATT&CK for ICS technique per scenario (mirrors backend/app/attacks/engine.py MITRE map --
// display-only here, the authoritative id still comes from the incident the backend reports).
const MITRE: Record<Scenario, { id: string; name: string }> = {
  sensor_freeze: { id: "T0856", name: "Spoof Reporting Message" },
  sensor_offset: { id: "T0856", name: "Spoof Reporting Message" },
  sensor_ramp: { id: "T0856", name: "Spoof Reporting Message" },
  actuator_force: { id: "T0831", name: "Manipulation of Control" },
  rogue_setpoint: { id: "T0855", name: "Unauthorized Command Message" },
};

const ICON: Record<Scenario, LucideIcon> = {
  sensor_freeze: Snowflake,
  sensor_offset: TrendingDown,
  sensor_ramp: TrendingUp,
  actuator_force: Zap,
  rogue_setpoint: Zap,
};

export function ScenarioPicker({
  scenarios,
  value,
  onChange,
}: {
  scenarios: readonly Scenario[];
  value: Scenario;
  onChange: (s: Scenario) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Scenario" className="flex flex-col gap-1.5">
      {scenarios.map((s) => {
        const Icon = ICON[s];
        const active = s === value;
        const mitre = MITRE[s];
        return (
          <Tooltip key={s} label={`${SCENARIO_LABEL[s]} · ${mitre.name}`}>
            <button
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(s)}
              className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-label transition-colors duration-fast ease-out ${
                active
                  ? "border-accent bg-accent-soft text-ink-1"
                  : "border-line-1 text-ink-2 hover:border-line-2 hover:text-ink-1"
              }`}
            >
              <Icon size={14} aria-hidden className={active ? "text-accent" : ""} />
              <span className="flex-1 text-left">{SCENARIO_LABEL[s]}</span>
              {/* Not tone="accent" here: the row itself is already accent-soft when active, and
                  stacking a second translucent accent-soft chip on top compounds to ~26% effective
                  opacity, dropping contrast to 4.0:1 (axe-flagged). Neutral reads fine against it. */}
              <Chip tone="neutral">{mitre.id}</Chip>
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
