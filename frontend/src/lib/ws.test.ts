import { describe, expect, it, vi } from "vitest";
import { latencyMs, pillKind } from "./pill";
import type { LiveMessage } from "./types";
import { BACKOFF_MAX_MS, backoffDelay, createLiveClient, liveUrl, parseMessage } from "./ws";

const msg: LiveMessage = {
  t: 1728300000.5,
  mode: "sim",
  nodes: [{ id: "LIT101", value: 62.4, truth: 62.1, score: 0.12, status: "normal" }],
  alert: null,
  incident: null,
  incidents: [],
  impact: null,
};

describe("parseMessage", () => {
  it("accepts a well-formed message", () => {
    expect(parseMessage(JSON.stringify(msg))).toEqual(msg);
  });

  it.each(["sim", "hai", "live"] as const)("accepts mode %s", (mode) => {
    expect(parseMessage(JSON.stringify({ ...msg, mode }))?.mode).toBe(mode);
  });

  it.each([
    ["not json", "{oops"],
    ["json scalar", "42"],
    ["null", "null"],
    ["missing t", JSON.stringify({ ...msg, t: undefined })],
    ["bad mode", JSON.stringify({ ...msg, mode: "xyz" })],
    ["nodes not array", JSON.stringify({ ...msg, nodes: {} })],
    ["node without value", JSON.stringify({ ...msg, nodes: [{ id: "A" }] })],
  ])("rejects %s", (_, raw) => {
    expect(parseMessage(raw)).toBeNull();
  });

  it("rejects non-string frames", () => {
    expect(parseMessage(new ArrayBuffer(4))).toBeNull();
  });
});

describe("backoffDelay", () => {
  it("doubles and caps", () => {
    expect([0, 1, 2, 3, 4, 5, 9].map(backoffDelay)).toEqual([
      500, 1000, 2000, 4000, 8000, 8000, 8000,
    ]);
    expect(backoffDelay(50)).toBe(BACKOFF_MAX_MS);
  });
});

describe("liveUrl", () => {
  it("follows the page protocol", () => {
    expect(liveUrl({ protocol: "http:", host: "a:5173" })).toBe("ws://a:5173/ws/live");
    expect(liveUrl({ protocol: "https:", host: "a" })).toBe("wss://a/ws/live");
  });

  it("omits the token query param when none is passed", () => {
    expect(liveUrl({ protocol: "http:", host: "a" })).toBe("ws://a/ws/live");
  });

  it("appends the operator token as a query param, URL-encoded", () => {
    expect(liveUrl({ protocol: "http:", host: "a" }, "tok 123")).toBe(
      "ws://a/ws/live?token=tok%20123",
    );
  });
});

class FakeSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  closed = false;
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

describe("createLiveClient", () => {
  it("reports states, delivers valid messages only, and reconnects with backoff", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const states: string[] = [];
    const got: LiveMessage[] = [];
    const stop = createLiveClient({
      url: "ws://x",
      onMessage: (m) => got.push(m),
      onState: (s) => states.push(s),
      socketFactory: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s as unknown as WebSocket;
      },
    });
    expect(states).toEqual(["connecting"]);
    sockets[0]?.onopen?.();
    sockets[0]?.onmessage?.({ data: JSON.stringify(msg) } as MessageEvent);
    sockets[0]?.onmessage?.({ data: "garbage" } as MessageEvent);
    expect(got).toEqual([msg]);

    sockets[0]?.onclose?.(); // server drops us
    expect(states.at(-1)).toBe("reconnecting");
    vi.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2); // retried after 500 ms

    sockets[1]?.onclose?.(); // second failure waits 1000 ms
    vi.advanceTimersByTime(999);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);

    sockets[2]?.onopen?.(); // success resets the backoff
    expect(states.at(-1)).toBe("live");
    sockets[2]?.onclose?.();
    vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(4);

    stop();
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(4); // closed for good
    vi.useRealTimers();
  });
});

describe("pillKind", () => {
  const incident = {
    id: "inc_001",
    status: "open" as const,
    detected_at: 0,
    origin: [],
    path: [],
    path_edges: [],
    explanation: "",
    action: "",
    mitre: "T0856",
    mitre_name: "",
    baseline_alarms: [],
    ground_truth: null,
  };

  it("puts connection state first", () => {
    expect(pillKind("connecting", msg)).toBe("connecting");
    expect(pillKind("reconnecting", msg)).toBe("offline");
  });

  it("then escalates normal -> alert -> incident", () => {
    expect(pillKind("live", msg)).toBe("normal");
    expect(pillKind("live", { ...msg, alert: { since: 1, score: 3, threshold: 2 } })).toBe("alert");
    expect(pillKind("live", { ...msg, incident })).toBe("incident");
    expect(pillKind("live", { ...msg, incident: { ...incident, status: "closed" } })).toBe(
      "normal",
    );
    expect(pillKind("live", null)).toBe("normal");
  });
});

describe("latencyMs", () => {
  it("is the clock difference, clamped at zero", () => {
    expect(latencyMs(100, 100_042)).toBe(42);
    expect(latencyMs(100, 99_000)).toBe(0);
  });
});
