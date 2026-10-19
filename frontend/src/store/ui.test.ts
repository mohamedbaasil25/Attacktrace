import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUi } from "./ui";

// Test environment is "node" (see vite.config.ts): no browser localStorage, so the store's own
// try/catch around it (see store/ui.ts) is exercised either way. Stub a minimal in-memory one
// to also verify the persistence path itself, not just the fallback.
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

let storage: Storage;

beforeEach(() => {
  storage = fakeStorage();
  vi.stubGlobal("localStorage", storage);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("viewRole", () => {
  it("defaults to analyst (today's full view)", () => {
    expect(useUi.getState().viewRole).toBe("analyst");
  });

  it("setViewRole updates state and persists to localStorage", () => {
    useUi.getState().setViewRole("operator");
    expect(useUi.getState().viewRole).toBe("operator");
    expect(storage.getItem("at_view_role")).toBe("operator");
    useUi.getState().setViewRole("analyst"); // leave global state as found for other tests
  });
});

describe("selectedIncidentId", () => {
  it("defaults to null and is never written to localStorage", () => {
    expect(useUi.getState().selectedIncidentId).toBeNull();
    useUi.getState().setSelectedIncidentId("inc_001");
    expect(useUi.getState().selectedIncidentId).toBe("inc_001");
    expect(storage.getItem("at_selected_incident")).toBeNull();
    useUi.getState().setSelectedIncidentId(null);
  });
});
