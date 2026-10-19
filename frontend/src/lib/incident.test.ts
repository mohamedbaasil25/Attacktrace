import { CircleHelp, LoaderCircle, ShieldAlert, ShieldCheck } from "lucide-react";
import { describe, expect, it } from "vitest";
import { STATUS_CHIP, elapsed, isActive, resolveSelected, statusIcon } from "./incident";
import type { Incident, OriginCandidate } from "./types";

function inc(id: string, status: Incident["status"] = "open"): Incident {
  const origin: OriginCandidate[] = [{ id: "LIT101", type: "sensor", confidence: 0.5 }];
  return {
    id,
    status,
    detected_at: 0,
    origin,
    path: [],
    path_edges: [],
    explanation: "",
    action: "",
    mitre: "T0856",
    mitre_name: "",
    baseline_alarms: [],
    ground_truth: null,
  };
}

describe("isActive", () => {
  it("is true only for localizing or open", () => {
    expect(isActive(inc("a", "localizing"))).toBe(true);
    expect(isActive(inc("a", "open"))).toBe(true);
    expect(isActive(inc("a", "closed"))).toBe(false);
    expect(isActive(inc("a", "contained"))).toBe(false);
    expect(isActive(null)).toBe(false);
    expect(isActive(undefined)).toBe(false);
  });
});

describe("elapsed", () => {
  it("formats seconds and minutes", () => {
    expect(elapsed(0, 5)).toBe("5s");
    expect(elapsed(0, 125)).toBe("2m 5s");
  });

  it("never goes negative", () => {
    expect(elapsed(10, 5)).toBe("0s");
  });
});

describe("resolveSelected", () => {
  const a = inc("inc_a");
  const b = inc("inc_b");

  it("returns the selected incident when it exists", () => {
    expect(resolveSelected([a, b], "inc_b")).toBe(b);
  });

  it("falls back to the first (most severe) when nothing is selected", () => {
    expect(resolveSelected([a, b], null)).toBe(a);
  });

  it("falls back to the first when the selection no longer exists (e.g. it closed)", () => {
    expect(resolveSelected([a, b], "inc_gone")).toBe(a);
  });

  it("returns null with no incidents open", () => {
    expect(resolveSelected([], "inc_a")).toBeNull();
  });
});

describe("STATUS_CHIP", () => {
  it("covers every incident status with a distinct tone", () => {
    const statuses: Incident["status"][] = ["localizing", "open", "contained", "closed"];
    for (const s of statuses) expect(STATUS_CHIP[s]).toBeDefined();
    const tones = statuses.map((s) => STATUS_CHIP[s].tone);
    expect(new Set(tones).size).toBe(tones.length);
  });
});

describe("statusIcon", () => {
  it("uses the status icon by default", () => {
    expect(statusIcon(inc("a", "open"))).toBe(ShieldAlert);
    expect(statusIcon(inc("a", "localizing"))).toBe(LoaderCircle);
    expect(statusIcon(inc("a", "contained"))).toBe(ShieldCheck);
  });

  it("overrides with CircleHelp when ambiguous, regardless of status", () => {
    const i = { ...inc("a", "open"), ambiguous: true };
    expect(statusIcon(i)).toBe(CircleHelp);
  });
});
