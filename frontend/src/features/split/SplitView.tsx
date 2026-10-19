import { motion, useReducedMotion } from "framer-motion";
import { Radar, ShieldCheck, TriangleAlert, Wrench } from "lucide-react";
import { EmptyState } from "../../components/ui/EmptyState";
import { isActive } from "../../lib/incident";
import type { Incident } from "../../lib/types";
import { selectView, useLive } from "../../store/live";
import { OriginCard } from "../incident/OriginCard";
import { PathChips } from "../incident/PathChips";

function Column({ title, count, children }: { title: string; count: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-8 items-center justify-between border-b border-line-1 px-2 text-xs">
        <span className="font-medium uppercase tracking-wide text-ink-3">{title}</span>
        <span className="font-mono text-ink-1">{count}</span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">{children}</div>
    </section>
  );
}

/** The 3-sigma baseline's view: every node it would flag, as a flood of red alarms. */
function BaselineAlarms({ incident }: { incident: Incident }) {
  const reduce = useReducedMotion();
  return (
    <ul className="flex flex-col gap-1">
      {incident.baseline_alarms.map((id, i) => (
        <motion.li
          key={id}
          initial={reduce ? false : { opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.2, delay: reduce ? 0 : i * 0.05 }}
          className="flex items-center gap-2 rounded-md border border-origin/40 bg-origin/10 px-2 py-1 text-origin"
        >
          <TriangleAlert size={14} aria-hidden />
          <span className="font-mono text-xs">{id}</span>
          <span className="ml-auto font-mono text-xs">3σ</span>
        </motion.li>
      ))}
    </ul>
  );
}

function Trace({ incident }: { incident: Incident }) {
  return (
    <div className="flex flex-col gap-3">
      <OriginCard incident={incident} />
      <PathChips incident={incident} />
      <p className="font-mono text-xs leading-snug text-ink-2">{incident.explanation}</p>
      <p className="flex items-center gap-1 text-xs text-affected">
        <Wrench size={12} aria-hidden />
        <span className="font-mono">{incident.action}</span>
      </p>
    </div>
  );
}

/** Same live data, two answers: how many alarms vs which single origin. */
export function SplitView() {
  const view = useLive(selectView);
  const incident = view?.incident ?? null;
  const active = isActive(incident) ? incident : null;
  const alarms = active?.baseline_alarms.length ?? 0;
  return (
    <div className="flex h-full divide-x divide-line-1">
      <Column title="Baseline" count={`${alarms} ${alarms === 1 ? "alarm" : "alarms"}`}>
        {active && alarms > 0 ? (
          <BaselineAlarms incident={active} />
        ) : (
          <EmptyState icon={ShieldCheck} text="No alarms" />
        )}
      </Column>
      <Column title="AttackTrace" count={active ? "1 origin" : "0 origins"}>
        {active ? <Trace incident={active} /> : <EmptyState icon={Radar} text="No incident" />}
      </Column>
    </div>
  );
}
