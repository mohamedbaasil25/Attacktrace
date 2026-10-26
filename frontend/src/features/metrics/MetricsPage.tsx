import { FileX, LoaderCircle, Lock, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavBar } from "../../app/NavBar";
import { Chip } from "../../components/ui/Chip";
import { EmptyState } from "../../components/ui/EmptyState";
import { Tooltip } from "../../components/ui/Tooltip";
import {
  f1Rows,
  parseMetrics,
  pct,
  type HaiMetrics,
  type LiveEvalMetrics,
  type Metrics,
} from "../../lib/metrics";
import { useAuth } from "../../store/auth";
import { MetricsChart } from "./MetricsChart";

type Load =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "unauthorized" }
  | { state: "ready"; metrics: Metrics };

/** AttackTrace vs the 3-sigma baseline on the same value; `better` says which direction counts
 *  as an improvement so the chip's arrow and tone (never colour alone) point the right way. */
interface Delta {
  value: number;
  baseline: number;
  better: "higher" | "lower";
  format: (n: number) => string;
}

function DeltaChip({ d }: { d: Delta }) {
  const diff = d.value - d.baseline;
  const good = d.better === "higher" ? diff >= 0 : diff <= 0;
  const Icon = diff >= 0 ? TrendingUp : TrendingDown;
  const sign = diff > 0 ? "+" : "";
  return (
    <Chip tone={good ? "normal" : "origin"} icon={<Icon size={11} aria-hidden />} title={`Baseline ${d.format(d.baseline)}`}>
      {sign}
      {d.format(diff)}
    </Chip>
  );
}

function Card({
  label,
  definition,
  value,
  delta,
  sub,
}: {
  label: string;
  definition: string;
  value: string;
  delta?: Delta;
  sub?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-line-1 bg-surface-1 p-3">
      <Tooltip label={definition}>
        <span tabIndex={0} className="cursor-help text-caption uppercase tracking-[0.04em] text-ink-3">
          {label}
        </span>
      </Tooltip>
      <span className="font-mono text-kpi font-medium text-ink-1">{value}</span>
      <div className="flex h-5 items-center gap-1">
        {delta && <DeltaChip d={delta} />}
        {sub && <span className="font-mono text-caption text-ink-3">{sub}</span>}
      </div>
    </div>
  );
}

function Cards({ m }: { m: Metrics }) {
  const { attacktrace: a, baseline: b } = m.detection;
  const loc = m.localization;
  const ttl = loc.mean_time_to_localize_s;
  const iso = m.isolation?.isolate_top1;
  const amb = m.ambiguity;
  return (
    <div className={`grid gap-2 ${iso && amb ? "grid-cols-7" : "grid-cols-5"}`}>
      <Card
        label="F1"
        definition="Harmonic mean of precision and recall on held-out attacks."
        value={a.f1.toFixed(2)}
        delta={{ value: a.f1, baseline: b.f1, better: "higher", format: (n) => n.toFixed(2) }}
      />
      <Card
        label="Top-1"
        definition="Share of incidents whose true origin ranked first."
        value={pct(loc.top1)}
        delta={loc.baseline ? { value: loc.top1, baseline: loc.baseline.top1, better: "higher", format: pct } : undefined}
      />
      <Card
        label="Top-3"
        definition="Share of incidents whose true origin was in the top 3."
        value={pct(loc.top3)}
        delta={loc.baseline ? { value: loc.top3, baseline: loc.baseline.top3, better: "higher", format: pct } : undefined}
      />
      <Card
        label="Time to localize"
        definition="Mean seconds from the first alert to a stable origin."
        value={ttl === null ? "–" : `${ttl.toFixed(1)} s`}
      />
      <Card
        label="False alarms"
        definition="Alerts per hour on clean, attack-free runs."
        value={`${a.false_alarm_per_hour.toFixed(1)} /h`}
        delta={{
          value: a.false_alarm_per_hour,
          baseline: b.false_alarm_per_hour,
          better: "lower",
          format: (n) => `${n.toFixed(1)} /h`,
        }}
      />
      {iso && (
        <Card
          label="Contained"
          definition="Share of isolate attempts that ended the incident."
          value={pct(iso.success_rate)}
          sub={`${iso.contained} of ${iso.n}`}
        />
      )}
      {amb && (
        <Card
          label="Ambiguous"
          definition="Share of incidents where the top two origins were too close to call."
          value={pct(amb.ambiguous_rate)}
          sub={`${amb.n_ambiguous} of ${amb.n_incidents}`}
        />
      )}
    </div>
  );
}

function HaiCards({ h }: { h: HaiMetrics }) {
  const { attacktrace: a, baseline: b, localization: l } = h;
  const maj = l.majority_process;
  return (
    <section aria-label="HAI results" className="mt-2 flex flex-col gap-2">
      <h2 className="font-mono text-caption uppercase tracking-[0.04em] text-ink-3">
        HAI · {h.files.join(", ")} · {h.active_model}
      </h2>
      <div className="grid grid-cols-5 gap-2">
        <Card
          label="F1"
          definition="Strict F1 on HAI held-out test days (exact timing, not point-adjusted)."
          value={a.f1.toFixed(2)}
          delta={{ value: a.f1, baseline: b.f1, better: "higher", format: (n) => n.toFixed(2) }}
          sub={`Adjusted ${a.f1_point_adjusted.toFixed(2)}`}
        />
        <Card
          label="Attacks detected"
          definition="Share of labelled attack windows that raised an alert."
          value={pct(a.windows_detected)}
          sub={`${Math.round(a.windows_detected * a.n_windows)} of ${a.n_windows}`}
        />
        <Card
          label="False alarms"
          definition="Alerts per hour on clean stretches of the test days."
          value={`${a.false_alarm_per_hour.toFixed(2)} /h`}
          delta={{
            value: a.false_alarm_per_hour,
            baseline: b.false_alarm_per_hour,
            better: "lower",
            format: (n) => `${n.toFixed(2)} /h`,
          }}
        />
        <Card
          label="Process Top-1"
          definition="Share of detected attacks whose labelled process ranked first."
          value={pct(l.process_top1)}
          sub={`Always ${maj} ${pct(l.always_majority_process)}`}
        />
        <Card
          label="Top-1 if detected"
          definition="Process Top-1 restricted to attacks the detector actually caught."
          value={l.process_top1_given_detected === null ? "–" : pct(l.process_top1_given_detected)}
          sub={
            l.always_majority_given_detected === null
              ? undefined
              : `Always ${maj} ${pct(l.always_majority_given_detected)}`
          }
        />
      </div>
    </section>
  );
}

function formatUptime(s: number | null): string {
  if (s === null) return "–";
  const m = s / 60;
  return m < 60 ? `${m.toFixed(0)} min` : `${(m / 60).toFixed(1)} h`;
}

/** The currently-running session's own false-alarm rate against the mode-appropriate documented
 *  baseline -- a cheap concept-drift signal, not a new metric: same data, same Card/DeltaChip. */
function SessionCard({ m }: { m: Metrics }) {
  const s = m.live_session;
  if (!s) return null;
  const baseline = s.mode === "sim" ? m.detection.attacktrace.false_alarm_per_hour : m.live?.detection.false_alarm_per_hour;
  return (
    <section aria-label="This session" className="grid grid-cols-5 gap-2">
      <Card
        label="Session false alarms"
        definition={`This running ${s.mode.toUpperCase()} session's own false-alarm rate, vs. the documented baseline.`}
        value={`${s.false_alarm_per_hour.toFixed(1)} /h`}
        delta={
          baseline !== undefined
            ? { value: s.false_alarm_per_hour, baseline, better: "lower", format: (n) => `${n.toFixed(1)} /h` }
            : undefined
        }
        sub={`Uptime ${formatUptime(s.uptime_s)}`}
      />
    </section>
  );
}

function LiveCards({ l }: { l: LiveEvalMetrics }) {
  return (
    <section aria-label="Live results" className="mt-2 flex flex-col gap-2">
      <h2 className="font-mono text-caption uppercase tracking-[0.04em] text-ink-3">
        Live · {l.n_attacks} attacks · {l.n_clean_runs} clean runs
      </h2>
      <div className="grid grid-cols-5 gap-2">
        <Card
          label="F1"
          definition="Detection F1 over real Modbus TCP against the plant emulator."
          value={l.detection.f1.toFixed(2)}
          sub={`P ${l.detection.precision.toFixed(2)} · R ${l.detection.recall.toFixed(2)}`}
        />
        <Card
          label="Top-1 / Top-3"
          definition="Share of LIVE incidents whose origin ranked first / in the top 3."
          value={`${pct(l.localization.top1)} / ${pct(l.localization.top3)}`}
        />
        <Card
          label="Latency"
          definition="Median end-to-end decision latency, sample to alert."
          value={`${l.latency_ms.p50.toFixed(0)} ms`}
          sub={`p95 ${l.latency_ms.p95.toFixed(0)} ms`}
        />
        <Card
          label="Samples/s"
          definition="Sustained ingestion rate from the plant emulator."
          value={l.samples_per_s.toFixed(0)}
          sub={`${l.dropped} dropped`}
        />
        <Card
          label="False alarms"
          definition="Alerts per hour with no attack running."
          value={`${l.detection.false_alarm_per_hour.toFixed(2)} /h`}
          sub={`Uptime ${formatUptime(l.uptime_s)}`}
        />
      </div>
    </section>
  );
}

export function MetricsPage() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Read directly from the store's current value: this page is reached by a full page
  // navigation (not client-side routing), so there's no React tree to subscribe through at
  // mount time -- the token itself is still available (sessionStorage), just not reactively.
  const authToken = useAuth((s) => s.token);

  useEffect(() => {
    let live = true;
    fetch("/api/metrics", authToken ? { headers: { authorization: `Bearer ${authToken}` } } : {})
      .then((r) => {
        if (r.status === 401) return "unauthorized" as const;
        return r.ok ? r.json() : null;
      })
      .then((raw: unknown) => {
        if (!live) return;
        if (raw === "unauthorized") {
          setLoad({ state: "unauthorized" });
          return;
        }
        const metrics = parseMetrics(raw);
        setLoad(metrics ? { state: "ready", metrics } : { state: "missing" });
      })
      .catch(() => live && setLoad({ state: "missing" }));
    return () => {
      live = false;
    };
  }, [authToken]);

  const rows = useMemo(() => (load.state === "ready" ? f1Rows(load.metrics) : []), [load]);

  return (
    <div className="flex h-full min-w-[1280px] flex-col bg-surface-0">
      <NavBar />
      <main className="flex min-h-0 flex-1 flex-col gap-2 p-4">
        {load.state === "loading" && <EmptyState icon={LoaderCircle} text="Loading" />}
        {load.state === "missing" && <EmptyState icon={FileX} text="Run make eval" />}
        {load.state === "unauthorized" && <EmptyState icon={Lock} text="Login required" />}
        {load.state === "ready" && (
          <>
            <Cards m={load.metrics} />
            <SessionCard m={load.metrics} />
            {load.metrics.hai && <HaiCards h={load.metrics.hai} />}
            {load.metrics.live && <LiveCards l={load.metrics.live} />}
            <section aria-label="F1 by scenario" className="min-h-0 flex-1 rounded-md border border-line-1 bg-surface-1 p-3">
              <MetricsChart rows={rows} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
