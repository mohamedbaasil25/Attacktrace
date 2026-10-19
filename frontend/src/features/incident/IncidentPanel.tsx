import { ArrowLeft, Eye, FileDown, ShieldAlert, ShieldCheck, WifiOff, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { LinkButton } from "../../components/ui/Button";
import { Chip } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { reportUrl } from "../../lib/api";
import { STATUS_CHIP, elapsed, resolveSelected, statusIcon } from "../../lib/incident";
import type { Incident } from "../../lib/types";
import type { ViewRole } from "../../store/ui";
import { selectView, useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { ImpactMeters } from "./ImpactMeters";
import { IncidentTriageList } from "./IncidentTriageList";
import { IsolateButton } from "./IsolateButton";
import { PathChips } from "./PathChips";
import { OriginCard } from "./OriginCard";

function Section({ children }: { children: React.ReactNode }) {
  return <div className="border-b border-line-1 p-2 last:border-b-0">{children}</div>;
}

function Reveal({ incident }: { incident: Incident }) {
  const [shown, setShown] = useState(false);
  const truth = incident.ground_truth;
  if (!truth) return null;
  const hit = incident.origin[0]?.id === truth.target;
  return (
    <button
      type="button"
      onClick={() => setShown((s) => !s)}
      className="flex w-full items-center gap-1 text-left text-xs text-ink-3 hover:text-ink-2"
    >
      <Eye size={12} aria-hidden />
      {shown ? (
        <span className="font-mono">
          {truth.attack_id} · {truth.target} · {truth.scenario} ·{" "}
          <span className={hit ? "text-normal" : "text-origin"}>{hit ? "hit" : "miss"}</span>
        </span>
      ) : (
        <span>Reveal</span>
      )}
    </button>
  );
}

function Details({
  incident,
  now,
  role,
}: {
  incident: Incident;
  now: number;
  role: ViewRole;
}) {
  const sc = STATUS_CHIP[incident.status];
  const Icon = statusIcon(incident);
  return (
    <>
      <Section>
        <div className="mb-1 flex items-center gap-1.5 text-xs">
          <Chip
            tone={incident.ambiguous ? "suspect" : sc.tone}
            icon={<Icon size={11} className={!incident.ambiguous && sc.spin ? "animate-spin" : ""} aria-hidden />}
            testId="incident-status"
          >
            {incident.ambiguous ? "Ambiguous" : sc.label}
          </Chip>
          <span className="font-mono text-ink-3">{elapsed(incident.detected_at, now)}</span>
          <span className="font-mono text-ink-3">{incident.id}</span>
          {incident.mitre && (
            <Chip tone="accent" title={incident.mitre_name}>
              {incident.mitre}
            </Chip>
          )}
          <LinkButton
            href={reportUrl(incident.id)}
            download
            aria-label="Report"
            title="Report (PDF)"
            variant="ghost"
            className="ml-auto h-8 w-8 px-0"
          >
            <FileDown size={14} aria-hidden />
          </LinkButton>
        </div>
        {role === "analyst" && <OriginCard incident={incident} />}
      </Section>
      {role === "analyst" && (
        <Section>
          <PathChips incident={incident} />
        </Section>
      )}
      <Section>
        <p className="font-mono text-xs leading-snug text-ink-2">{incident.explanation}</p>
        <p className="mt-1 flex items-center gap-1 text-xs text-affected">
          <Wrench size={12} aria-hidden />
          <span className="font-mono">{incident.action}</span>
        </p>
        <div className="mt-2">
          <IsolateButton incident={incident} />
        </div>
      </Section>
      {role === "analyst" && (
        <Section>
          <Reveal incident={incident} />
        </Section>
      )}
    </>
  );
}

export function IncidentPanel() {
  const conn = useLive((s) => s.conn);
  const latest = useLive(selectView);
  const hasStream = useLive((s) => s.latest !== null);
  const role = useUi((s) => s.viewRole);
  const selectedId = useUi((s) => s.selectedIncidentId);
  const setSelectedId = useUi((s) => s.setSelectedIncidentId);
  const live = (conn === "live" || hasStream) && latest !== null;
  const incidents = latest?.incidents ?? [];
  const now = latest?.t ?? 0;
  const active = incidents.length > 0;
  const selected = resolveSelected(incidents, selectedId);

  let body: ReactNode;
  if (incidents.length === 0) {
    body = (
      <div className="h-20 border-b border-line-1">
        <EmptyState icon={ShieldCheck} text="All nominal" />
      </div>
    );
  } else if (incidents.length === 1 && incidents[0]) {
    body = <Details incident={incidents[0]} now={now} role={role} />;
  } else if (selectedId !== null && selected !== null) {
    body = (
      <>
        <Section>
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink-1"
          >
            <ArrowLeft size={12} aria-hidden />
            Back to incidents
          </button>
        </Section>
        <Details incident={selected} now={now} role={role} />
      </>
    );
  } else {
    body = <IncidentTriageList incidents={incidents} now={now} onSelect={setSelectedId} />;
  }

  return (
    <Panel title="Incident" icon={active ? ShieldAlert : ShieldCheck}>
      {!live ? (
        <EmptyState icon={WifiOff} text="No signal" />
      ) : (
        <div className="flex h-full flex-col overflow-y-auto">
          {body}
          <Section>
            <ImpactMeters impact={latest.impact} />
          </Section>
        </div>
      )}
    </Panel>
  );
}
