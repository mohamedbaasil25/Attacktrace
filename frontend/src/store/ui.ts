import { create } from "zustand";

export type CenterView = "twin" | "graph";
export type ViewRole = "operator" | "analyst";

const OPERATOR_KEY = "at_operator";
const ROLE_KEY = "at_view_role";

function readStoredOperator(): string {
  try {
    return localStorage.getItem(OPERATOR_KEY) ?? "";
  } catch {
    return "";
  }
}

function readStoredRole(): ViewRole {
  try {
    return localStorage.getItem(ROLE_KEY) === "operator" ? "operator" : "analyst";
  } catch {
    return "analyst";
  }
}

interface UiState {
  view: CenterView;
  /** Baseline vs AttackTrace side by side, replacing the twin/graph pane. */
  split: boolean;
  /** One-line notice (e.g. "Demo locked"); cleared by the toast after a few seconds. */
  notice: { text: string; id: number } | null;
  /** Node clicked in the console's node list; the twin draws a focus ring around it. */
  focusedNode: string | null;
  /** Who's at the console right now; gates Isolate and is attached to the incident/report.
   *  Per-browser convenience only (localStorage), not authentication. */
  operatorName: string;
  /** Operator vs analyst: gates how much forensic detail the incident panel shows.
   *  Per-browser convenience (localStorage), defaults to "analyst" (today's full view). */
  viewRole: ViewRole;
  /** Which open incident the triage list, twin and graph highlight. Ephemeral: not persisted,
   *  resets to the most severe (index 0) on reload or when the selection closes. */
  selectedIncidentId: string | null;
  setView: (v: CenterView) => void;
  toggleSplit: () => void;
  notify: (text: string) => void;
  clearNotice: () => void;
  toggleFocusedNode: (id: string) => void;
  setOperatorName: (name: string) => void;
  setViewRole: (role: ViewRole) => void;
  setSelectedIncidentId: (id: string | null) => void;
}

let noticeId = 0;

export const useUi = create<UiState>((set) => ({
  view: "twin",
  split: false,
  notice: null,
  focusedNode: null,
  operatorName: readStoredOperator(),
  viewRole: readStoredRole(),
  selectedIncidentId: null,
  setView: (view) => set({ view }),
  toggleSplit: () => set((s) => ({ split: !s.split })),
  notify: (text) => set({ notice: { text, id: ++noticeId } }),
  clearNotice: () => set({ notice: null }),
  toggleFocusedNode: (id) => set((s) => ({ focusedNode: s.focusedNode === id ? null : id })),
  setOperatorName: (name) => {
    try {
      localStorage.setItem(OPERATOR_KEY, name);
    } catch {
      /* best effort; the field still works for this tab's session */
    }
    set({ operatorName: name });
  },
  setViewRole: (role) => {
    try {
      localStorage.setItem(ROLE_KEY, role);
    } catch {
      /* best effort; the toggle still works for this tab's session */
    }
    set({ viewRole: role });
  },
  setSelectedIncidentId: (id) => set({ selectedIncidentId: id }),
}));

/** Shows `Demo locked` for an API 401/403; returns true when it did. */
export function noticeIfLocked(e: unknown): boolean {
  const locked = typeof e === "object" && e !== null && (e as { locked?: unknown }).locked === true;
  if (locked) useUi.getState().notify("Demo locked");
  return locked;
}
