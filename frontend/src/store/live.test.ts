import { beforeEach, describe, expect, it } from "vitest";
import type { LiveMessage } from "../lib/types";
import { RING_CAPACITY, pushRing, selectView, useLive } from "./live";

const mk = (t: number): LiveMessage => ({
  t,
  mode: "sim",
  nodes: [],
  alert: null,
  incident: null,
  incidents: [],
  impact: null,
});

describe("pushRing", () => {
  it("appends without mutating the input", () => {
    const a = [1, 2];
    const b = pushRing(a, 3, 5);
    expect(b).toEqual([1, 2, 3]);
    expect(a).toEqual([1, 2]);
  });

  it("drops the oldest once full", () => {
    expect(pushRing([1, 2, 3], 4, 3)).toEqual([2, 3, 4]);
  });
});

describe("live store", () => {
  beforeEach(() => {
    useLive.setState({ conn: "connecting", buffer: [], latest: null, receivedAt: null });
  });

  it("keeps a 5-minute ring (600 samples at 2 Hz)", () => {
    expect(RING_CAPACITY).toBe(600);
    for (let i = 0; i < RING_CAPACITY + 25; i++) useLive.getState().push(mk(i), 1000 + i);
    const s = useLive.getState();
    expect(s.buffer).toHaveLength(RING_CAPACITY);
    expect(s.buffer[0]?.t).toBe(25);
    expect(s.latest?.t).toBe(RING_CAPACITY + 24);
    expect(s.receivedAt).toBe(1000 + RING_CAPACITY + 24);
  });

  it("tracks connection state", () => {
    useLive.getState().setConn("live");
    expect(useLive.getState().conn).toBe("live");
  });
});

describe("replay cursor", () => {
  const reset = () =>
    useLive.setState({ buffer: [], latest: null, cursor: null, playing: false, conn: "connecting" });
  const fill = (n: number) => {
    for (let i = 0; i < n; i++) useLive.getState().push(mk(i), i);
  };

  it("scrubbing pins the view and pauses playback", () => {
    reset();
    fill(10);
    useLive.getState().scrubTo(3);
    expect(useLive.getState().cursor).toBe(3);
    expect(selectView(useLive.getState())?.t).toBe(3);
    useLive.getState().push(mk(10), 10);
    expect(selectView(useLive.getState())?.t).toBe(3); // live data keeps arriving, the view stays
    useLive.getState().scrubTo(999);
    expect(useLive.getState().cursor).toBe(10); // clamped
  });

  it("follows the live sample when there is no cursor", () => {
    reset();
    fill(4);
    expect(selectView(useLive.getState())?.t).toBe(3);
  });

  it("plays forward and returns to live at the end", () => {
    reset();
    fill(5);
    const s = useLive.getState();
    s.scrubTo(3);
    s.play();
    useLive.getState().tick();
    expect(useLive.getState().cursor).toBe(4 - 0);
    useLive.getState().tick();
    expect(useLive.getState().cursor).toBeNull();
    expect(useLive.getState().playing).toBe(false);
  });

  it("pause freezes the live stream at the newest sample; goLive releases it", () => {
    reset();
    fill(5);
    useLive.getState().pause();
    expect(useLive.getState().cursor).toBe(4);
    useLive.getState().goLive();
    expect(useLive.getState().cursor).toBeNull();
  });

  it("keeps pointing at the same sample when the ring drops the oldest", () => {
    reset();
    fill(RING_CAPACITY);
    useLive.getState().scrubTo(100);
    const t = selectView(useLive.getState())?.t;
    useLive.getState().push(mk(RING_CAPACITY), 0);
    expect(useLive.getState().cursor).toBe(99);
    expect(selectView(useLive.getState())?.t).toBe(t);
  });

  it("replays from 20 s before the incident", () => {
    reset();
    for (let i = 0; i < 100; i++) {
      const incident = i >= 70 ? ({ id: "inc_001" } as unknown as LiveMessage["incident"]) : null;
      useLive.getState().push({ ...mk(i), incident }, i);
    }
    useLive.getState().replayIncident();
    expect(useLive.getState().cursor).toBe(30); // 70 - 40-sample lead
    expect(useLive.getState().playing).toBe(true);
  });
});
