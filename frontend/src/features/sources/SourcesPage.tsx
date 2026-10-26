import { FileX, LoaderCircle, Lock, Radio } from "lucide-react";
import { useEffect, useState } from "react";
import { NavBar } from "../../app/NavBar";
import { Chip, type Tone } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { getLiveHealth, getStatus } from "../../lib/api";
import type { Quality, Status, TagHealth } from "../../lib/types";
import { useAuth } from "../../store/auth";

type Load =
  | { state: "loading" }
  | { state: "error" }
  | { state: "ready"; status: Status; health: TagHealth[] | null; healthLocked: boolean };

const QUALITY_TONE: Record<Quality, Tone> = {
  good: "normal",
  stale: "suspect",
  missing: "origin",
  out_of_range: "origin",
  frozen: "suspect",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-line-1 bg-surface-1 p-3">
      <span className="font-mono text-caption uppercase tracking-[0.04em] text-ink-3">{label}</span>
      <span className="font-mono text-sm text-ink-1">{value}</span>
    </div>
  );
}

export function SourcesPage() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const authToken = useAuth((s) => s.token);

  useEffect(() => {
    let live = true;
    getStatus()
      .then((status) =>
        status.mode === "live"
          ? getLiveHealth(authToken || undefined)
              .then((health) => ({ health, healthLocked: false }))
              .catch((e: unknown) => ({
                health: null,
                healthLocked: (e as { status?: number }).status === 401,
              }))
              .then(({ health, healthLocked }) => ({ status, health, healthLocked }))
          : { status, health: null, healthLocked: false },
      )
      .then((r) => live && setLoad({ state: "ready", ...r }))
      .catch(() => live && setLoad({ state: "error" }));
    return () => {
      live = false;
    };
  }, [authToken]);

  return (
    <div className="flex h-full min-w-[1024px] flex-col bg-surface-0">
      <NavBar />
      <main className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <h1 className="text-title font-semibold tracking-tight text-ink-1">Sources</h1>
        {load.state === "loading" && <EmptyState icon={LoaderCircle} text="Loading" />}
        {load.state === "error" && <EmptyState icon={FileX} text="Could not load" />}
        {load.state === "ready" && (
          <>
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Mode" value={load.status.mode.toUpperCase()} />
              <Stat label="Protocol" value={load.status.source?.protocol ?? "internal"} />
              <Stat
                label="Connection"
                value={load.status.source?.connected ? "connected" : (load.status.source?.state ?? "n/a")}
              />
              <Stat
                label="Samples/s"
                value={load.status.source?.samples_per_s?.toFixed(0) ?? "–"}
              />
            </div>
            {load.status.mode !== "live" ? (
              <section className="flex flex-col items-center gap-3 rounded-md border border-line-1 bg-surface-1 px-6 py-10 text-center">
                <Radio size={28} className="text-ink-3" aria-hidden />
                <div className="flex flex-col gap-1">
                  <span className="text-label font-medium text-ink-1">
                    Tag health tracks LIVE mode only
                  </span>
                  <span className="max-w-sm text-caption text-ink-3">
                    Per-tag data quality (stale, missing, out of range) only applies while
                    AttackTrace is reading real Modbus data. In {load.status.mode.toUpperCase()}{" "}
                    mode there's no external source to monitor.
                  </span>
                </div>
                <a
                  href="/"
                  className="mt-1 text-label text-accent transition-colors duration-fast ease-out hover:text-ink-1"
                >
                  Switch mode on Monitoring →
                </a>
              </section>
            ) : (
              <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-line-1 bg-surface-1">
                <header className="flex h-8 shrink-0 items-center gap-1 border-b border-line-1 px-2 text-xs font-medium uppercase tracking-wide text-ink-2">
                  <Radio size={14} aria-hidden />
                  <span>Tag health</span>
                </header>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {load.healthLocked && <EmptyState icon={Lock} text="Login required" />}
                  {!load.healthLocked && (load.health?.length ?? 0) === 0 && (
                    <EmptyState icon={FileX} text="No tags" />
                  )}
                  {!load.healthLocked && load.health && load.health.length > 0 && (
                    <div className="flex flex-col">
                      {load.health.map((h) => (
                        <div
                          key={h.tag}
                          className="grid grid-cols-[1fr_140px_120px_120px] items-center gap-3 border-b border-line-1 px-3 py-2 text-label text-ink-2"
                        >
                          <span className="truncate font-mono text-ink-1">{h.tag}</span>
                          <span className="font-mono text-caption text-ink-3">{h.node_id}</span>
                          <Chip tone={QUALITY_TONE[h.quality]}>{h.quality}</Chip>
                          <span className="font-mono text-caption text-ink-3">
                            {h.age_ms === null ? "–" : `${h.age_ms} ms`}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
