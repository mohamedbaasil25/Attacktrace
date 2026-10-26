import {
  FileDown,
  FileX,
  LoaderCircle,
  Lock,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavBar } from "../../app/NavBar";
import { Chip, type Tone } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { getEvidenceVerification, getIncidents, reportUrl } from "../../lib/api";
import type { Incident, IncidentStatus, VerifyLedgerResponse } from "../../lib/types";
import { useAuth } from "../../store/auth";
import { OriginCard } from "../incident/OriginCard";
import { PathChips } from "../incident/PathChips";

type Load =
  | { state: "loading" }
  | { state: "unauthorized" }
  | { state: "error" }
  | { state: "ready"; incidents: Incident[] };

const STATUS_TONE: Record<IncidentStatus, Tone> = {
  localizing: "suspect",
  open: "origin",
  contained: "accent",
  closed: "neutral",
};

const STATUS_DOT: Record<IncidentStatus, string> = {
  localizing: "bg-suspect",
  open: "bg-origin",
  contained: "bg-accent",
  closed: "bg-ink-3",
};

const ACTIVE_STATUSES = new Set<IncidentStatus>(["localizing", "open", "contained"]);

function selectedId(): string | null {
  return new URLSearchParams(window.location.search).get("id");
}

/** A snapshot "time ago" for a page fetched once -- see AlertsPage's identical helper. */
function timeAgo(unixS: number, nowS: number): string {
  const s = Math.max(0, Math.round(nowS - unixS));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function EvidenceCard({ authToken }: { authToken: string }) {
  const [v, setV] = useState<VerifyLedgerResponse | "unauthorized" | "unavailable" | null>(null);
  useEffect(() => {
    let live = true;
    getEvidenceVerification(authToken || undefined)
      .then((r) => live && setV(r))
      .catch((e: unknown) =>
        live && setV((e as { status?: number }).status === 401 ? "unauthorized" : "unavailable"),
      );
    return () => {
      live = false;
    };
  }, [authToken]);
  if (v === null) return null;
  if (v === "unauthorized") return <Chip tone="neutral">Evidence: login required</Chip>;
  if (v === "unavailable") return <Chip tone="neutral">Evidence: unavailable</Chip>;
  const ok = v.status === "verified";
  return (
    <Chip tone={ok ? "normal" : "origin"} icon={ok ? <ShieldCheck size={11} /> : <ShieldX size={11} />}>
      Evidence {v.status} · {v.checked} checked
    </Chip>
  );
}

function Detail({ incident, authToken }: { incident: Incident; authToken: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="flex items-center gap-2">
        <h2 className="font-mono text-sm font-medium text-ink-1">{incident.id}</h2>
        <Chip tone={STATUS_TONE[incident.status]}>{incident.status}</Chip>
        <Chip tone="neutral">{incident.mitre_name}</Chip>
        <EvidenceCard authToken={authToken} />
        <a
          href={reportUrl(incident.id)}
          className="ml-auto flex items-center gap-1 text-label text-ink-3 transition-colors duration-fast ease-out hover:text-ink-1"
        >
          <FileDown size={14} aria-hidden />
          PDF report
        </a>
      </div>
      <OriginCard incident={incident} />
      <section className="rounded-md border border-line-1 bg-surface-1 p-3">
        <h3 className="mb-2 font-mono text-caption uppercase tracking-[0.04em] text-ink-3">
          Propagation path
        </h3>
        <PathChips incident={incident} orientation="horizontal" />
      </section>
      <section className="flex flex-col gap-1 rounded-md border border-line-1 bg-surface-1 p-3">
        <h3 className="font-mono text-caption uppercase tracking-[0.04em] text-ink-3">Explanation</h3>
        <p className="text-label text-ink-1">{incident.explanation}</p>
        <h3 className="mt-2 font-mono text-caption uppercase tracking-[0.04em] text-ink-3">
          Recommended action
        </h3>
        <p className="text-label text-ink-1">{incident.action}</p>
      </section>
    </div>
  );
}

export function InvestigationsPage() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [selected, setSelected] = useState<string | null>(() => selectedId());
  const authToken = useAuth((s) => s.token);

  useEffect(() => {
    let live = true;
    getIncidents(authToken || undefined)
      .then((incidents) => live && setLoad({ state: "ready", incidents }))
      .catch((e: unknown) => {
        if (!live) return;
        const status = (e as { status?: number }).status;
        setLoad({ state: status === 401 ? "unauthorized" : "error" });
      });
    return () => {
      live = false;
    };
  }, [authToken]);

  const incidents = load.state === "ready" ? load.incidents : [];
  const current = incidents.find((i) => i.id === selected) ?? incidents[0] ?? null;
  const activeCount = incidents.filter((i) => ACTIVE_STATUSES.has(i.status)).length;
  const now = Date.now() / 1000;

  return (
    <div className="flex h-full min-w-[1200px] flex-col bg-surface-0">
      <NavBar />
      <main className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-2">
          <h1 className="text-title font-semibold tracking-tight text-ink-1">Investigations</h1>
          {load.state === "ready" && (
            <Chip tone="neutral">
              {incidents.length} total{activeCount > 0 ? ` · ${activeCount} active` : ""}
            </Chip>
          )}
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-[340px_minmax(0,1fr)] gap-3">
          <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-line-1 bg-surface-1">
            <header className="flex h-8 shrink-0 items-center gap-1 border-b border-line-1 px-2 text-xs font-medium uppercase tracking-wide text-ink-2">
              <Search size={14} aria-hidden />
              <span>Incidents</span>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {load.state === "loading" && <EmptyState icon={LoaderCircle} text="Loading" />}
              {load.state === "unauthorized" && <EmptyState icon={Lock} text="Login required" />}
              {load.state === "error" && <EmptyState icon={FileX} text="Could not load" />}
              {load.state === "ready" &&
                incidents.map((i) => {
                  const top1 = i.origin[0];
                  const active = ACTIVE_STATUSES.has(i.status);
                  const isSelected = current?.id === i.id;
                  return (
                    <button
                      key={i.id}
                      type="button"
                      onClick={() => {
                        setSelected(i.id);
                        window.history.replaceState(
                          null,
                          "",
                          `/investigations?id=${encodeURIComponent(i.id)}`,
                        );
                      }}
                      className={`flex w-full items-center gap-2 border-b border-line-1 px-3 py-2.5 text-left transition-colors duration-fast ease-out hover:bg-surface-2 ${
                        isSelected ? "border-l-2 border-l-accent bg-surface-2" : "border-l-2 border-l-transparent"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[i.status]} ${
                          active ? "animate-pulse" : ""
                        }`}
                        aria-hidden
                      />
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`truncate font-mono text-caption ${
                              isSelected ? "text-ink-1" : "text-ink-2"
                            }`}
                          >
                            {i.id}
                          </span>
                          {active && <ShieldAlert size={10} className="shrink-0 text-origin" aria-hidden />}
                        </div>
                        <span className="truncate font-mono text-[10px] text-ink-3">
                          {top1 ? `${top1.id} · ${Math.round(top1.confidence * 100)}%` : "–"}
                        </span>
                      </div>
                      <span className="shrink-0 font-mono text-[10px] text-ink-3">
                        {timeAgo(i.detected_at, now)}
                      </span>
                    </button>
                  );
                })}
            </div>
          </section>
          <section className="min-h-0 overflow-hidden rounded-md border border-line-1 bg-surface-1">
            {current ? (
              <Detail incident={current} authToken={authToken} />
            ) : (
              <EmptyState icon={Search} text="Select an incident" />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
