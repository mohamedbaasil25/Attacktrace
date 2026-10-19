import { describe, expect, it } from "vitest";
import { IDLE, NOT_CONTAINED_MS, advance, begin, candidateFor, disabledReason, refused } from "./isolate";
import type { Incident, IncidentStatus } from "./types";

function inc(status: IncidentStatus, id = "inc_001", extra: Partial<Incident> = {}): Incident {
  const c = (n: string) => ({ id: n, type: "sensor" as const, confidence: 0.3 });
  return {
    id,
    status,
    detected_at: 0,
    origin: [c("LIT101"), c("PLC1"), c("MV101")],
    path: [],
    path_edges: [],
    explanation: "",
    action: "",
    mitre: "",
    mitre_name: "",
    baseline_alarms: [],
    ground_truth: null,
    ...extra,
  };
}

describe("candidateFor", () => {
  it("offers the best candidate, then the next one after a failed try", () => {
    expect(candidateFor(inc("open"), [])).toBe("LIT101");
    expect(candidateFor(inc("open"), ["LIT101"])).toBe("PLC1");
    expect(candidateFor(inc("open"), ["LIT101", "PLC1", "MV101"])).toBeNull();
  });
});

describe("isolate state machine", () => {
  const open = inc("open");
  it("idle -> pending once the server applied the action", () => {
    const s = begin(IDLE, open, "LIT101", 1000);
    expect(s).toMatchObject({ phase: "pending", node: "LIT101", tried: ["LIT101"], since: 1000 });
  });

  it("pending -> contained only when the incident says so, with its time", () => {
    const s = begin(IDLE, open, "LIT101", 0);
    expect(advance(s, inc("open"), 5_000).phase).toBe("pending"); // not on a timer
    const done = advance(s, inc("contained", "inc_001", { time_to_contain_s: 12.5 }), 8_000);
    expect(done).toMatchObject({ phase: "contained", seconds: 12.5 });
  });

  it("pending -> failed after the timeout, never to contained", () => {
    const s = begin(IDLE, open, "PLC2", 0);
    expect(advance(s, open, NOT_CONTAINED_MS - 1).phase).toBe("pending");
    const failed = advance(s, open, NOT_CONTAINED_MS);
    expect(failed.phase).toBe("failed");
    expect(candidateFor(open, failed.tried)).toBe("LIT101"); // PLC2 is not a candidate: first try
  });

  it("pending -> failed when the incident closes by itself", () => {
    const s = begin(IDLE, open, "PLC1", 0);
    expect(advance(s, inc("closed"), 1_000).phase).toBe("failed");
  });

  it("a failed try is followed by the next candidate", () => {
    const failed = advance(begin(IDLE, open, "LIT101", 0), open, NOT_CONTAINED_MS);
    const again = begin(failed, open, candidateFor(open, failed.tried) ?? "", 40_000);
    expect(again).toMatchObject({ phase: "pending", node: "PLC1", tried: ["LIT101", "PLC1"] });
  });

  it("resets when the incident changes or disappears", () => {
    const s = begin(IDLE, open, "LIT101", 0);
    expect(advance(s, inc("open", "inc_002"), 100)).toEqual(IDLE);
    expect(advance(s, null, 100)).toEqual(IDLE);
  });

  it("keeps the refusal reason without leaving idle", () => {
    expect(refused(IDLE, "Node already isolated")).toMatchObject({
      phase: "idle",
      note: "Node already isolated",
    });
  });
});

describe("disabledReason (Phase 13: LIVE is read-only)", () => {
  const open = inc("open");
  const closed = inc("closed");
  const none = { hai: false, live: false, replaying: false, operatorSet: true };

  it("is clickable for an active incident with nothing in the way", () => {
    expect(disabledReason(open, none)).toBeNull();
  });

  it("reads exactly 'Read-only' in LIVE mode, ahead of anything else", () => {
    expect(disabledReason(open, { ...none, live: true })).toBe("Read-only");
    expect(disabledReason(closed, { ...none, live: true })).toBe("Read-only");
    expect(disabledReason(open, { hai: true, live: true, replaying: true, operatorSet: true })).toBe(
      "HAI replay is read-only", // hai is checked first; both can never be true together in practice
    );
  });

  it("falls back to replay and incident-state reasons outside LIVE and HAI", () => {
    expect(disabledReason(open, { ...none, replaying: true })).toBe("Replay is read-only");
    expect(disabledReason(closed, none)).toBe("Incident is not active");
  });

  it("asks for an operator name before the incident-active check", () => {
    expect(disabledReason(open, { ...none, operatorSet: false })).toBe("Set operator name (top bar)");
    // still read-only/replay reasons win when those are also true
    expect(disabledReason(open, { ...none, operatorSet: false, replaying: true })).toBe(
      "Replay is read-only",
    );
  });
});
