import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "./auth";

// Test environment is "node" (see vite.config.ts): no browser sessionStorage; stub a minimal
// in-memory one, same pattern as store/ui.test.ts.
function fakeStorage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => data.set(k, v),
    removeItem: (k: string) => data.delete(k),
    clear: () => data.clear(),
    get length() {
      return data.size;
    },
    key: (i: number) => Array.from(data.keys())[i] ?? null,
  } as Storage;
}

beforeEach(() => {
  vi.stubGlobal("sessionStorage", fakeStorage());
  vi.stubGlobal("fetch", vi.fn());
  useAuth.setState({ token: "", username: "", role: null, pending: false, error: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAuth", () => {
  it("defaults to logged out", () => {
    expect(useAuth.getState().token).toBe("");
    expect(useAuth.getState().role).toBeNull();
  });

  it("login stores the token, username and role on success", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          token: "tok123",
          username: "alice",
          role: "operator",
          expires_in_s: 28800,
        }),
        { status: 200 },
      ),
    );
    await useAuth.getState().login("alice", "secret");
    const s = useAuth.getState();
    expect(s.token).toBe("tok123");
    expect(s.username).toBe("alice");
    expect(s.role).toBe("operator");
    expect(s.pending).toBe(false);
  });

  it("login sets an error on failure and leaves the token empty", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid username or password" }), { status: 401 }),
    );
    await useAuth.getState().login("alice", "wrong");
    const s = useAuth.getState();
    expect(s.token).toBe("");
    expect(s.error).toBe("Invalid username or password");
  });

  it("logout clears the stored identity", async () => {
    useAuth.setState({ token: "tok123", username: "alice", role: "operator" });
    useAuth.getState().logout();
    const s = useAuth.getState();
    expect(s.token).toBe("");
    expect(s.username).toBe("");
    expect(s.role).toBeNull();
  });
});
