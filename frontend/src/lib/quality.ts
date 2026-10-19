import { AlertTriangle, Clock, HelpCircle, Snowflake } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Quality } from "./types";

/** One shape per quality problem, distinct from the node status glyphs, so colour is never the
 *  only cue. `good` has no icon: nothing is drawn for it. */
export const QUALITY_ICON: Partial<Record<Quality, LucideIcon>> = {
  stale: Clock,
  missing: HelpCircle,
  out_of_range: AlertTriangle,
  frozen: Snowflake,
};

export const QUALITY_LABEL: Record<Quality, string> = {
  good: "Good",
  stale: "Stale",
  missing: "Missing",
  out_of_range: "Out of range",
  frozen: "Frozen",
};

/** Human age for a tooltip, from TagHealth.age_ms. */
export function ageLabel(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "age unknown";
  if (ms < 1000) return `${Math.round(ms)} ms old`;
  return `${(ms / 1000).toFixed(1)} s old`;
}
