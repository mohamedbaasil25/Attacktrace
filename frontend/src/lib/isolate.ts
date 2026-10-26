import { isActive } from "./incident";
import type { Incident } from "./types";

/** How long a pending isolate action may take before the UI calls it `Not contained`. The eval
 *  contained the true origin after 13.9 s of plant time on average (reports/metrics.json). */
export const NOT_CONTAINED_MS = 30_000;

export type IsoPhase = "idle" | "pending" | "contained" | "failed";

export interface IsoState {
  phase: IsoPhase;
  incidentId: string | null;
  /** Nodes already isolated for this incident, so a retry offers the next candidate. */
  tried: string[];
  node: string | null; // the node of the latest action
  since: number | null; // Date.now() when it was accepted
  seconds: number | null; // plant seconds the backend took to contain
  note: string | null; // why the server refused the last action
}

export const IDLE: IsoState = {
  phase: "idle",
  incidentId: null,
  tried: [],
  node: null,
  since: null,
  seconds: null,
  note: null,
};

/** Best-ranked candidate that has not been isolated yet. */
export function candidateFor(inc: Incident, tried: readonly string[]): string | null {
  return inc.origin.find((c) => !tried.includes(c.id))?.id ?? null;
}

export interface IsolateAvailability {
  hai: boolean;
  live: boolean;
  replaying: boolean;
  /** An operator name is set at the top bar, or (when `authRequired`) a verified login token is
   *  present. Isolate is attributed, never anonymous. */
  operatorSet: boolean;
  /** AT_AUTH_SECRET is configured server-side (Status.auth_required): the operator-name field
   *  alone no longer reads as sufficient, only a logged-in token does. Defaults false. */
  authRequired?: boolean;
}

/** Why the Isolate button is disabled right now, or null when it may be clicked. AttackTrace
 *  never writes to a real or LIVE plant: HAI is a read-only replay and LIVE is read-only by
 *  design (§2.3), so both disable the button outright, before the incident state is even checked. */
export function disabledReason(incident: Incident, a: IsolateAvailability): string | null {
  if (a.hai) return "HAI replay is read-only";
  if (a.live) return "Read-only";
  if (a.replaying) return "Replay is read-only";
  if (!a.operatorSet) return a.authRequired ? "Log in to isolate (top bar)" : "Set operator name (top bar)";
  if (!isActive(incident)) return "Incident is not active";
  return null;
}

/** How a failed isolate request should be shown, decided from the HTTP status alone (kept pure
 *  and separate from IsolateButton so it's testable without rendering). `hadToken` distinguishes
 *  "never logged in" from "the token we sent was rejected" -- only the latter is a stale session
 *  worth clearing. Returns null for anything not auth-shaped, so the caller falls through to its
 *  existing generic-error handling (e.g. the demo API-key lock). */
export function classifyIsolateError(
  status: number,
  authRequired: boolean,
  hadToken: boolean,
): { logout: boolean; note: string } | null {
  if (!authRequired || (status !== 401 && status !== 403)) return null;
  if (status === 403) return { logout: false, note: "Your role cannot isolate" };
  return hadToken
    ? { logout: true, note: "Session expired, please log in again (top bar)" }
    : { logout: false, note: "Log in to isolate (top bar)" };
}

/** The server applied the action: wait for containment. */
export function begin(s: IsoState, inc: Incident, node: string, now: number): IsoState {
  const tried = s.incidentId === inc.id ? s.tried : [];
  return {
    phase: "pending",
    incidentId: inc.id,
    tried: [...tried, node],
    node,
    since: now,
    seconds: null,
    note: null,
  };
}

export function refused(s: IsoState, reason: string): IsoState {
  return { ...s, note: reason };
}

/** Transition on each new live message (and clock reading). Containment is only ever read from
 *  the incident the backend reports; nothing here decides that the plant recovered. */
export function advance(s: IsoState, inc: Incident | null, now: number): IsoState {
  if (s.incidentId !== null && inc?.id !== s.incidentId) return IDLE; // another incident, or none
  if (s.phase !== "pending" || inc === null || s.since === null) return s;
  if (inc.status === "contained") {
    return { ...s, phase: "contained", seconds: inc.time_to_contain_s ?? null };
  }
  if (inc.status === "closed" || now - s.since >= NOT_CONTAINED_MS) return { ...s, phase: "failed" };
  return s;
}
