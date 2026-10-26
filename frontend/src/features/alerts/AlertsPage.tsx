import { Bell, FileX, LoaderCircle, Lock, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavBar } from "../../app/NavBar";
import { Chip, type Tone } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { getIncidents } from "../../lib/api";
import type { Incident, IncidentStatus } from "../../lib/types";
import { useAuth } from "../../store/auth";

type Load =
  | { state: "loading" }
  | { state: "unauthorized" }
  | { state: "error" }
  | { state: "ready"; incidents: Incident[] };

type Filter = "all" | "active" | "closed";

const STATUS_TONE: Record<IncidentStatus, Tone> = {
  localizing: "suspect",
  open: "origin",
  contained: "accent",
  closed: "neutral",
};

const ACTIVE_STATUSES = new Set<IncidentStatus>(["localizing", "open", "contained"]);

function fmtTime(unixS: number): string {
  return new Date(unixS * 1000).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** A snapshot "time ago" for a page fetched once -- doesn't need to tick live like the
 *  dashboard's `elapsed()`, just needs to read fast on a list of mostly-old incidents. */
function timeAgo(unixS: number, nowS: number): string {
  const s = Math.max(0, Math.round(nowS - unixS));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "origin" | "normal" }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-line-1 bg-surface-1 px-3 py-2">
      <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-ink-3">{label}</span>
      <span
        className={`font-mono text-kpi font-medium ${
          tone === "origin" && value > 0 ? "text-origin" : tone === "normal" ? "text-normal" : "text-ink-1"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function OriginBar({ confidence }: { confidence: number }) {
  return (
    <div className="h-1 w-14 overflow-hidden rounded-full bg-line-1" aria-hidden>
      <div
        className="h-full rounded-full bg-origin"
        style={{ width: `${Math.round(confidence * 100)}%` }}
      />
    </div>
  );
}

function Row({ incident, now }: { incident: Incident; now: number }) {
  const top1 = incident.origin[0];
  const active = ACTIVE_STATUSES.has(incident.status) && incident.status !== "contained";
  return (
    <a
      href={`/investigations?id=${encodeURIComponent(incident.id)}`}
      className={`grid grid-cols-[1fr_120px_220px_160px_180px_90px] items-center gap-3 border-b border-line-1 px-3 py-2.5 text-label text-ink-2 transition-colors duration-fast ease-out hover:bg-surface-2 hover:text-ink-1 ${
        active ? "bg-origin/5" : ""
      }`}
    >
      <span className={`truncate font-mono ${active ? "font-medium text-origin" : "text-ink-1"}`}>
        {incident.id}
      </span>
      <Chip
        tone={STATUS_TONE[incident.status]}
        icon={active ? <ShieldAlert size={11} aria-hidden /> : undefined}
      >
        {incident.status}
      </Chip>
      <span className="flex items-center gap-2 truncate">
        {top1 ? (
          <>
            <span className="text-ink-1">{top1.id}</span>
            <OriginBar confidence={top1.confidence} />
            <span className="font-mono text-caption text-ink-3">
              {Math.round(top1.confidence * 100)}%
            </span>
          </>
        ) : (
          "–"
        )}
      </span>
      <Chip tone="neutral">{incident.mitre_name}</Chip>
      <span className="font-mono text-caption text-ink-3" title={fmtTime(incident.detected_at)}>
        {timeAgo(incident.detected_at, now)}
      </span>
      <span className="uppercase text-ink-3">{incident.mode ?? "sim"}</span>
    </a>
  );
}

export function AlertsPage() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [filter, setFilter] = useState<Filter>("all");
  const authToken = useAuth((s) => s.token);
  const now = useMemo(() => Date.now() / 1000, []);

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
  const activeCount = incidents.filter((i) => ACTIVE_STATUSES.has(i.status)).length;
  const shown = incidents.filter((i) => {
    if (filter === "active") return ACTIVE_STATUSES.has(i.status);
    if (filter === "closed") return i.status === "closed";
    return true;
  });

  return (
    <div className="flex h-full min-w-[1024px] flex-col bg-surface-0">
      <NavBar />
      <main className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <h1 className="text-title font-semibold tracking-tight text-ink-1">Alerts</h1>
          {load.state === "ready" && (
            <div className="ml-auto flex items-center gap-2">
              <Stat label="Total" value={incidents.length} />
              <Stat label="Active" value={activeCount} tone="origin" />
              <Stat label="Closed" value={incidents.length - activeCount} tone="normal" />
              <SegmentedControl<Filter>
                aria-label="Filter alerts"
                layoutId="alerts-filter"
                value={filter}
                onChange={setFilter}
                segments={[
                  { value: "all", label: "All" },
                  { value: "active", label: "Active" },
                  { value: "closed", label: "Closed" },
                ]}
              />
            </div>
          )}
        </div>
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-line-1 bg-surface-1">
          <div className="grid grid-cols-[1fr_120px_220px_160px_180px_90px] gap-3 border-b border-line-1 bg-surface-2 px-3 py-2 font-mono text-caption uppercase tracking-[0.04em] text-ink-3">
            <span>Incident</span>
            <span>Status</span>
            <span>Top origin</span>
            <span>MITRE</span>
            <span>Detected</span>
            <span>Mode</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {load.state === "loading" && <EmptyState icon={LoaderCircle} text="Loading" />}
            {load.state === "unauthorized" && <EmptyState icon={Lock} text="Login required" />}
            {load.state === "error" && <EmptyState icon={FileX} text="Could not load" />}
            {load.state === "ready" && incidents.length === 0 && (
              <EmptyState icon={Bell} text="No incidents yet" />
            )}
            {load.state === "ready" && incidents.length > 0 && shown.length === 0 && (
              <EmptyState icon={ShieldCheck} text="Nothing matches" />
            )}
            {load.state === "ready" && shown.map((i) => <Row key={i.id} incident={i} now={now} />)}
          </div>
        </section>
      </main>
    </div>
  );
}
