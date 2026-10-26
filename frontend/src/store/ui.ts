import { create } from "zustand";

export type CenterView = "twin" | "graph";
export type ViewRole = "operator" | "analyst";
export type Theme = "dark" | "light";

const OPERATOR_KEY = "at_operator";
const ROLE_KEY = "at_view_role";
const THEME_KEY = "at_theme";

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

/** Reads the DOM attribute `index.html`'s inline script already applied before React mounted
 *  (same source of truth, not a second localStorage read that could disagree with what's
 *  actually painted). Wrapped like the readers above: this module loads in non-DOM test
 *  environments too, where `document` itself is undefined, not just empty. */
function readCurrentTheme(): Theme {
  try {
    return document.documentElement.dataset.theme === "light" ? "light" : "dark";
  } catch {
    return "dark";
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
  /** Ask AI's global slide-over (`AskAiDrawer`, rendered once per page by `NavBar`). A page-local
   *  React state would do too, but this lets any other component (e.g. the Incident panel's own
   *  "Ask AI" button) open the same drawer without prop-drilling a setter down to it. */
  askAiOpen: boolean;
  /** Dark is the default and the only theme anyone sees until they opt into light (NavBar's
   *  toggle); persisted to localStorage and applied pre-paint by index.html's inline script, the
   *  standard no-flash trick. */
  theme: Theme;
  setView: (v: CenterView) => void;
  toggleSplit: () => void;
  notify: (text: string) => void;
  clearNotice: () => void;
  toggleFocusedNode: (id: string) => void;
  setOperatorName: (name: string) => void;
  setViewRole: (role: ViewRole) => void;
  setSelectedIncidentId: (id: string | null) => void;
  setAskAiOpen: (open: boolean) => void;
  setTheme: (theme: Theme) => void;
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
  askAiOpen: false,
  theme: readCurrentTheme(),
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
  setAskAiOpen: (askAiOpen) => set({ askAiOpen }),
  setTheme: (theme) => {
    try {
      if (theme === "light") {
        document.documentElement.dataset.theme = "light";
      } else {
        delete document.documentElement.dataset.theme;
      }
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* best effort; the in-memory state below still updates this tab's session */
    }
    set({ theme });
  },
}));

/** Shows `Demo locked` for an API 401/403; returns true when it did. */
export function noticeIfLocked(e: unknown): boolean {
  const locked = typeof e === "object" && e !== null && (e as { locked?: unknown }).locked === true;
  if (locked) useUi.getState().notify("Demo locked");
  return locked;
}
