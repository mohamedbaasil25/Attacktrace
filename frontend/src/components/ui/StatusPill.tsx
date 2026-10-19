import { motion, useReducedMotion } from "framer-motion";
import { CircleCheck, LoaderCircle, ShieldAlert, TriangleAlert, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { PILL_LABEL, type PillKind } from "../../lib/pill";

const STYLE: Record<PillKind, { icon: LucideIcon; tone: string }> = {
  connecting: { icon: LoaderCircle, tone: "text-accent border-accent" },
  offline: { icon: WifiOff, tone: "text-ink-2 border-line-1" },
  normal: { icon: CircleCheck, tone: "text-normal border-normal" },
  alert: { icon: TriangleAlert, tone: "text-suspect border-suspect" },
  incident: { icon: ShieldAlert, tone: "text-origin border-origin" },
};

/** Status is always icon + label, never colour alone. */
export function StatusPill({ kind }: { kind: PillKind }) {
  const reduce = useReducedMotion();
  const { icon: Icon, tone } = STYLE[kind];
  return (
    <motion.span
      key={kind}
      role="status"
      aria-label={`Status ${PILL_LABEL[kind]}`}
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
      className={`inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs font-medium ${tone}`}
    >
      <Icon size={14} aria-hidden className={kind === "connecting" ? "animate-spin" : ""} />
      {PILL_LABEL[kind]}
    </motion.span>
  );
}
