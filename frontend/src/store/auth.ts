import { create } from "zustand";
import { ApiError, postLogin } from "../lib/api";
import type { ViewRole } from "./ui";

const TOKEN_KEY = "at_auth_token";
const USER_KEY = "at_auth_username";
const ROLE_KEY = "at_auth_role";

function readStored(key: string): string {
  try {
    return sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeStored(values: Record<string, string>): void {
  try {
    for (const [k, v] of Object.entries(values)) sessionStorage.setItem(k, v);
  } catch {
    /* best effort; the session still works for this tab */
  }
}

function clearStored(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(ROLE_KEY);
  } catch {
    /* best effort */
  }
}

interface AuthState {
  /** The operator's session token (Production Transition Roadmap, Phase 1), or "" when not
   *  logged in -- only meaningful when the server has AT_AUTH_SECRET configured; otherwise
   *  /api/isolate falls back to trusting the operator-name field as before. Session-scoped
   *  (sessionStorage), not persisted across browser restarts like operatorName is. */
  token: string;
  username: string;
  role: ViewRole | null;
  pending: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: readStored(TOKEN_KEY),
  username: readStored(USER_KEY),
  role: (readStored(ROLE_KEY) || null) as ViewRole | null,
  pending: false,
  error: null,
  login: async (username, password) => {
    set({ pending: true, error: null });
    try {
      const r = await postLogin(username, password);
      writeStored({ [TOKEN_KEY]: r.token, [USER_KEY]: r.username, [ROLE_KEY]: r.role });
      set({ token: r.token, username: r.username, role: r.role, pending: false });
    } catch (e) {
      set({ pending: false, error: e instanceof ApiError ? e.message : "Login failed" });
    }
  },
  logout: () => {
    clearStored();
    set({ token: "", username: "", role: null, error: null });
  },
}));
