import { describe, expect, it } from "vitest";
import type { Incident, TopologyEdge } from "../../lib/types";
import { PULSE_STAGGER_S } from "../twin/geometry";
import { edgeDelay, edgeId, layoutEdges, visibleEdges } from "./edges";

const incident = (over: Partial<Incident> = {}): Incident => ({
  id: "inc_001",
  status: "open",
  detected_at: 0,
  origin: [],
  path: [
    { id: "LIT101", t: 0, deviation: 1 },
    { id: "PLC1", t: 0, deviation: 0.8 },
    { id: "MV101", t: 1, deviation: 0.7 },
  ],
  path_edges: [
    ["LIT101", "PLC1"],
    ["PLC1", "MV101"],
  ],
  explanation: "",
  action: "",
  mitre: "T0856",
  mitre_name: "",
  baseline_alarms: [],
  ground_truth: null,
  ...over,
});

describe("edgeDelay", () => {
  it("is null off the path, with no incident, or once closed", () => {
    expect(edgeDelay("LIT101", "FIT201", incident())).toBeNull();
    expect(edgeDelay("LIT101", "PLC1", null)).toBeNull();
    expect(edgeDelay("LIT101", "PLC1", incident({ status: "closed" }))).toBeNull();
  });

  it("orders pulses by onset and keeps same-sample onsets sequential", () => {
    const a = edgeDelay("LIT101", "PLC1", incident());
    const b = edgeDelay("PLC1", "MV101", incident());
    expect(a).toBe(0);
    expect(b).toBeCloseTo(PULSE_STAGGER_S); // both onsets are 0 s, yet the second runs later
    expect(b ?? 0).toBeGreaterThan(a ?? 1);
  });
});

describe("visibleEdges", () => {
  const e = (src: string, dst: string, kind: TopologyEdge["kind"], weight: number): TopologyEdge => ({
    src,
    dst,
    kind,
    weight,
  });
  it("keeps every static edge and only strong learned edges", () => {
    const edges = [e("A", "B", "static", 1), e("A", "C", "learned", 0.1), e("B", "C", "learned", 0.4)];
    expect(visibleEdges(edges).map(edgeId)).toEqual(["A->B", "B->C"]);
  });
});

describe("a plant without a P&ID (HAI)", () => {
  const e = (src: string, dst: string, weight: number): TopologyEdge => ({ src, dst, kind: "learned", weight });
  const hai = [e("A", "B", 0.06), e("B", "C", 0.5)];

  it("shows and lays out every learned edge, however weak", () => {
    expect(visibleEdges(hai).map(edgeId)).toEqual(["A->B", "B->C"]);
    expect(layoutEdges(hai).map(edgeId)).toEqual(["A->B", "B->C"]);
  });

  it("with a P&ID the layout follows static edges only", () => {
    const mixed: TopologyEdge[] = [{ src: "A", dst: "B", kind: "static", weight: 1 }, e("B", "C", 0.9)];
    expect(layoutEdges(mixed).map(edgeId)).toEqual(["A->B"]);
  });
});
