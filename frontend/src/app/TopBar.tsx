import { ChartColumn, Columns2, User } from "lucide-react";
import { useEffect, useState } from "react";
import { AboutPopover } from "../components/ui/AboutPopover";
import { Logo } from "../components/ui/Logo";
import { ModeToggle } from "../components/ui/ModeToggle";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { SourcePill } from "../components/ui/SourcePill";
import { StatusPill } from "../components/ui/StatusPill";
import { getTopology, setMode as postMode } from "../lib/api";
import { latencyMs, pillKind } from "../lib/pill";
import type { Mode } from "../lib/types";
import { useLive } from "../store/live";
import type { ViewRole } from "../store/ui";
import { useUi } from "../store/ui";

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now.toLocaleTimeString("en-GB", { hour12: false });
}

export function TopBar() {
  const conn = useLive((s) => s.conn);
  const latest = useLive((s) => s.latest);
  const status = useLive((s) => s.status);
  const setStatus = useLive((s) => s.setStatus);
  const setTopology = useLive((s) => s.setTopology);
  const clear = useLive((s) => s.clear);
  const split = useUi((s) => s.split);
  const toggleSplit = useUi((s) => s.toggleSplit);
  const operatorName = useUi((s) => s.operatorName);
  const setOperatorName = useUi((s) => s.setOperatorName);
  const viewRole = useUi((s) => s.viewRole);
  const setViewRole = useUi((s) => s.setViewRole);
  const clock = useClock();
  const live = conn === "live" && latest !== null;
  const latency = live ? latencyMs(latest.t, Date.now()) : null;
  const mode = latest?.mode ?? status?.mode ?? "sim";

  const change = (m: Mode) => {
    postMode(m)
      .then(async (s) => {
        setStatus(s);
        clear(); // the old mode's history does not belong on the new timeline
        setTopology(await getTopology());
      })
      .catch(() => undefined);
  };

  return (
    // Wraps onto a second line below `lg` instead of overflowing or clipping -- the fixed h-14
    // single row is restored at `lg` to match the original pixel-locked layout exactly.
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line-1 bg-surface-1 px-3 py-2 lg:h-14 lg:flex-nowrap lg:py-0">
      <div className="flex items-center gap-1.5">
        <Logo size={20} />
        <h1 className="text-title font-semibold tracking-tight text-ink-1">AttackTrace</h1>
      </div>
      <ModeToggle
        mode={mode}
        haiAvailable={status?.hai_available ?? false}
        liveAvailable={status?.live_available ?? false}
        liveReason={status?.live_reason}
        onChange={change}
      />
      <StatusPill kind={pillKind(conn, latest)} />
      {latest?.mode === "live" && status?.source && <SourcePill source={status.source} />}
      <button
        type="button"
        aria-pressed={split}
        aria-label="Split view"
        onClick={toggleSplit}
        title="Baseline vs AttackTrace"
        className={`flex h-8 items-center gap-1 rounded-sm border px-2 text-label transition-colors duration-fast ease-out focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
          split ? "border-accent text-accent" : "border-line-1 text-ink-2 hover:text-ink-1"
        }`}
      >
        <Columns2 size={14} aria-hidden />
        Split
      </button>
      <a
        href="/metrics"
        className="flex h-8 items-center gap-1 rounded-sm border border-line-1 px-2 text-label text-ink-2 transition-colors duration-fast ease-out hover:text-ink-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <ChartColumn size={14} aria-hidden />
        Metrics
      </a>
      <div className="ml-auto flex items-center gap-3 font-mono text-label text-ink-2">
        <SegmentedControl<ViewRole>
          aria-label="View role"
          layoutId="role-indicator"
          value={viewRole}
          onChange={setViewRole}
          segments={[
            { value: "analyst", label: "analyst" },
            { value: "operator", label: "operator" },
          ]}
        />
        <label className="flex h-8 items-center gap-1 rounded-sm border border-line-1 px-2 text-ink-3 focus-within:border-line-2">
          <User size={12} aria-hidden />
          <input
            value={operatorName}
            onChange={(e) => setOperatorName(e.target.value)}
            placeholder="Operator"
            aria-label="Operator name"
            title="Required to Isolate; attached to the incident and the report"
            className="w-24 bg-transparent text-ink-1 placeholder:text-ink-3 focus:outline-none"
          />
        </label>
        <span title="Detector">{status?.detector_active ?? "–"}</span>
        <span title="Latency" className="w-14 text-right">
          {latency === null ? "–" : `${latency} ms`}
        </span>
        <time className="tabular-nums text-ink-1">{clock}</time>
        <AboutPopover mode={mode} />
      </div>
    </header>
  );
}
