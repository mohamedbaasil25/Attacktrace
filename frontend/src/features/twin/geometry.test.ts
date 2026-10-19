import { describe, expect, it } from "vitest";
import type { NodeState } from "../../lib/types";
import {
  LINKS,
  PULSE_STAGGER_S,
  flowDuration,
  flowRatio,
  pulseDelay,
  spinDuration,
} from "./geometry";

const node = (id: string, value: number, truth: number | null = value): NodeState => ({
  id,
  value,
  truth,
  score: 0,
  status: "normal",
});
const link = (id: string) => {
  const l = LINKS.find((x) => x.id === id);
  if (!l) throw new Error(id);
  return l;
};

describe("flow and spin mapping", () => {
  it("uses physical truth, scaled and clamped", () => {
    const nodes = new Map([["FIT201", node("FIT201", 99, 6)]]); // reported value is spoofed
    expect(flowRatio(link("f1"), nodes)).toBeCloseTo(0.5);
    expect(flowRatio(link("f1"), new Map([["FIT201", node("FIT201", 0, 40)]]))).toBe(1);
    expect(flowRatio(link("f1"), new Map())).toBe(0);
    expect(flowRatio(link("c1"), nodes)).toBe(0); // control lines carry no flow
  });

  it("faster flow and speed give shorter cycles; zero stops", () => {
    expect(flowDuration(0)).toBeNull();
    expect(flowDuration(1)).toBeCloseTo(0.6);
    expect(flowDuration(0.2) ?? 0).toBeGreaterThan(flowDuration(0.8) ?? 99);
    expect(spinDuration(0)).toBeNull();
    expect(spinDuration(1)).toBeCloseTo(0.4);
    expect(spinDuration(0.3) ?? 0).toBeGreaterThan(spinDuration(0.9) ?? 99);
  });
});

describe("pulseDelay", () => {
  const path = [
    { id: "LIT101", t: 0, deviation: 1 },
    { id: "PLC1", t: 1.5, deviation: 0.8 },
    { id: "MV101", t: 2, deviation: 0.7 },
  ];
  const edges: [string, string][] = [
    ["LIT101", "PLC1"],
    ["PLC1", "MV101"],
  ];

  it("delays each link by its source node onset plus its place in the path", () => {
    expect(pulseDelay(link("c1"), edges, path)).toBe(0);
    expect(pulseDelay(link("c2"), edges, path)).toBeCloseTo(1.5 + PULSE_STAGGER_S);
  });

  it("keeps same-sample onsets strictly sequential", () => {
    const tied = path.map((p) => ({ ...p, t: 0 }));
    const d1 = pulseDelay(link("c1"), edges, tied) ?? -1;
    const d2 = pulseDelay(link("c2"), edges, tied) ?? -1;
    expect(d2).toBeGreaterThan(d1);
  });

  it("ignores links that are not on the path", () => {
    expect(pulseDelay(link("c3"), edges, path)).toBeNull();
    expect(pulseDelay(link("f1"), edges, path)).toBeNull();
    expect(pulseDelay(link("c1"), [], [])).toBeNull();
  });
});

describe("link catalogue", () => {
  it("has unique ids and every pipe has a flow driver", () => {
    expect(new Set(LINKS.map((l) => l.id)).size).toBe(LINKS.length);
    expect(LINKS.filter((l) => l.kind === "pipe").every((l) => l.flow)).toBe(true);
  });
});
