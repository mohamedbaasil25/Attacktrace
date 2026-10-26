import { CircleHelp, Cog, Cpu, Gauge } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Chip } from "../../components/ui/Chip";
import { Ring } from "../../components/ui/Ring";
import type { Incident, NodeKind, OriginCandidate } from "../../lib/types";
import { BreakdownBar, BreakdownLegend } from "./BreakdownBar";

const KIND_ICON: Record<NodeKind, LucideIcon> = { sensor: Gauge, actuator: Cog, controller: Cpu };

const pct = (x: number): string => `${Math.round(x * 100)}%`;

/** Top 3 with equal weight: the top two are too close to trust a single answer. */
function Ambiguous({ incident }: { incident: Incident }) {
  return (
    <div className="flex flex-col gap-2" data-testid="ambiguous">
      <div className="flex items-center gap-2 text-suspect">
        <CircleHelp size={20} aria-hidden />
        <span className="text-base font-medium">Ambiguous</span>
        <span className="ml-auto text-xs text-ink-2">Top 3</span>
      </div>
      <ul className="flex flex-col gap-2">
        {incident.origin.slice(0, 3).map((c) => {
          const Icon = KIND_ICON[c.type];
          return (
            <li key={c.id} className="flex flex-col gap-1" data-testid={`candidate-${c.id}`}>
              <div className="flex items-center gap-2 font-mono">
                <Icon size={14} className="text-suspect" aria-hidden />
                <span>{c.id}</span>
                <span className="text-xs text-ink-2">{c.type}</span>
                <span className="ml-auto">{pct(c.confidence)}</span>
              </div>
              <BreakdownBar c={c} />
            </li>
          );
        })}
      </ul>
      <BreakdownLegend />
    </div>
  );
}

function RankRow({ c, rank }: { c: OriginCandidate; rank: number }) {
  return (
    <li className="flex flex-col gap-1">
      <div className="flex font-mono text-xs text-ink-2">
        <span className="w-4">{rank}</span>
        <span>{c.id}</span>
        <span className="ml-auto">{pct(c.confidence)}</span>
      </div>
      <BreakdownBar c={c} />
    </li>
  );
}

export function OriginCard({ incident }: { incident: Incident }) {
  const [top, ...rest] = incident.origin;
  if (!top) return null;
  if (incident.ambiguous) return <Ambiguous incident={incident} />;
  const Icon = KIND_ICON[top.type];
  // The confidence gate only flags "Ambiguous" when the top two scores are close enough to miss a
  // wrong guess most of the time it matters (held-out: it catches 2 of 8 wrong-Top-1 cases on the
  // test set). Showing the actual margin here, not just that binary flag, lets an operator judge
  // a narrow call for themselves even when the gate itself doesn't fire.
  const second = rest[0];
  const margin = second ? top.confidence - second.confidence : null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <Ring value={top.confidence} size={56} strokeWidth={5} tone="origin">
          <span className="font-mono text-caption font-medium text-ink-1" aria-hidden>
            {pct(top.confidence)}
          </span>
        </Ring>
        <div className="flex flex-col gap-0.5 leading-tight">
          <span data-testid="origin-id" className="font-mono text-value font-semibold text-origin">
            {top.id}
          </span>
          <div className="flex items-center gap-1.5">
            <Chip tone="origin" icon={<Icon size={11} aria-hidden />}>
              {top.type}
            </Chip>
            {second && margin !== null && (
              <span
                data-testid="origin-margin"
                className="font-mono text-xs text-ink-2"
                title={`Confidence margin over the #2 candidate (${second.id}): a narrow margin means the ranking is less certain, even when the gate didn't flag it`}
              >
                +{pct(margin)} margin
              </span>
            )}
          </div>
        </div>
        <span className="sr-only" aria-live="polite">
          {`Incident: ${top.id} origin, confidence ${pct(top.confidence)}`}
        </span>
      </div>
      {top.breakdown && (
        <>
          <BreakdownBar c={top} />
          <BreakdownLegend />
        </>
      )}
      {rest.length > 0 && (
        <ul className="flex flex-col gap-1">
          {rest.slice(0, 2).map((c, i) => (
            <RankRow key={c.id} c={c} rank={i + 2} />
          ))}
        </ul>
      )}
    </div>
  );
}
