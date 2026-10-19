import { motion, useReducedMotion } from "framer-motion";
import { Cable, CircleDot, LoaderCircle, Radio, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { SourceInfo } from "../../lib/types";

const STYLE: Record<SourceInfo["state"], { icon: LucideIcon; tone: string; label: string }> = {
  connected: { icon: Radio, tone: "text-normal border-normal", label: "Live" },
  stale: { icon: CircleDot, tone: "text-suspect border-suspect", label: "Stale" },
  connecting: { icon: LoaderCircle, tone: "text-accent border-accent", label: "Connecting" },
  down: { icon: WifiOff, tone: "text-origin border-origin", label: "Down" },
  calibrating: { icon: Cable, tone: "text-accent border-accent", label: "Calibrating" },
};

/** LIVE source health: connection state is icon + label, never colour alone. p50 latency and
 *  samples/s are appended once connected, e.g. "Live · 38 ms · 20/s". */
export function SourcePill({ source }: { source: SourceInfo }) {
  const reduce = useReducedMotion();
  const { icon: Icon, tone, label } = STYLE[source.state];
  const p50 = source.latency_ms_p50;
  const detail =
    source.state === "connected" && p50 !== null && p50 !== undefined
      ? ` · ${Math.round(p50)} ms · ${Math.round(source.samples_per_s ?? 0)}/s`
      : "";
  return (
    <motion.span
      key={source.state}
      role="status"
      aria-label={`Source ${label}`}
      title={source.reason ?? undefined}
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
      className={`inline-flex h-6 items-center gap-1 rounded-full border px-2 font-mono text-xs ${tone}`}
    >
      <Icon size={14} aria-hidden className={source.state === "connecting" ? "animate-spin" : ""} />
      {label}
      {detail}
    </motion.span>
  );
}
