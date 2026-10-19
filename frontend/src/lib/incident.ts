import { CircleHelp, LoaderCircle, ShieldAlert, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Tone as ChipTone } from "../components/ui/Chip";
import type { Incident } from "./types";

/** An incident that is still being worked: localizing or open (not closed, not contained). */
export const isActive = (inc: Incident | null | undefined): inc is Incident =>
  inc !== null && inc !== undefined && (inc.status === "localizing" || inc.status === "open");

/** Status chip vocabulary shared by the single-incident `Details` header and each row of the
 *  triage list -- same icon, label and tone wherever an incident's status is shown. */
export const STATUS_CHIP: Record<
  Incident["status"],
  { icon: LucideIcon; label: string; tone: ChipTone; spin?: boolean }
> = {
  localizing: { icon: LoaderCircle, label: "Localizing", tone: "suspect", spin: true },
  open: { icon: ShieldAlert, label: "Incident", tone: "origin" },
  contained: { icon: ShieldCheck, label: "Contained", tone: "normal" },
  closed: { icon: ShieldCheck, label: "Normal", tone: "neutral" },
};

/** The icon for an incident's status chip, accounting for the ambiguous override (shown instead
 *  of the status icon, never alongside it). */
export function statusIcon(inc: Pick<Incident, "status" | "ambiguous">): LucideIcon {
  return inc.ambiguous ? CircleHelp : STATUS_CHIP[inc.status].icon;
}

export function elapsed(startS: number, nowS: number): string {
  const s = Math.max(0, Math.round(nowS - startS));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** Which of several open incidents the twin/graph/panel should highlight: the one explicitly
 *  selected in the triage list, falling back to the most severe (index 0, the backend's own
 *  sort) when nothing is selected or the selection no longer exists (e.g. it just closed). */
export function resolveSelected(incidents: Incident[], selectedId: string | null): Incident | null {
  return incidents.find((i) => i.id === selectedId) ?? incidents[0] ?? null;
}
