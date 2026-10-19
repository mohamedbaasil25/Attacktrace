import { describe, expect, it } from "vitest";
import { groupLayout, layerLayout, processOf } from "./layout";

const IDS = ["LIT101", "MV101", "P101", "FIT201", "PIT301", "LIT301", "P301", "PLC1", "PLC2"];
const PID: [string, string][] = [
  ["LIT101", "PLC1"],
  ["PLC1", "MV101"],
  ["PLC1", "P101"],
  ["MV101", "LIT101"],
  ["P101", "LIT101"],
  ["P101", "FIT201"],
  ["LIT101", "FIT201"],
  ["FIT201", "PIT301"],
  ["FIT201", "LIT301"],
  ["LIT301", "PIT301"],
  ["LIT301", "FIT201"],
  ["LIT301", "PLC2"],
  ["PLC2", "P301"],
  ["P301", "LIT301"],
];
const edges = PID.map(([src, dst]) => ({ src, dst }));

describe("layerLayout", () => {
  const pos = layerLayout(IDS, edges);

  it("places every node exactly once, on distinct coordinates", () => {
    expect(Object.keys(pos).sort()).toEqual([...IDS].sort());
    const keys = new Set(Object.values(pos).map((p) => `${p.x},${p.y}`));
    expect(keys.size).toBe(IDS.length);
  });

  it("flows left to right along the control chain despite the feedback loops", () => {
    const x = (id: string) => pos[id]?.x ?? NaN;
    expect(x("LIT101")).toBeLessThan(x("PLC1"));
    expect(x("PLC1")).toBeLessThan(x("MV101"));
    expect(x("PLC1")).toBeLessThan(x("P101"));
    expect(x("P101")).toBeLessThan(x("FIT201"));
    expect(x("FIT201")).toBeLessThan(x("PIT301"));
    expect(x("LIT301")).toBeLessThan(x("PLC2"));
    expect(x("PLC2")).toBeLessThan(x("P301"));
  });

  it("is deterministic", () => {
    expect(layerLayout(IDS, edges)).toEqual(pos);
  });

  it("separates nodes that share a layer and centres each column", () => {
    const sameLayer = IDS.filter((id) => pos[id]?.x === pos.MV101?.x);
    const ys = sameLayer.map((id) => pos[id]?.y ?? 0);
    expect(new Set(ys).size).toBe(ys.length);
    expect(ys.reduce((a, b) => a + b, 0)).toBeCloseTo(0);
  });

  it("handles isolated nodes and ignores edges to unknown nodes", () => {
    const p = layerLayout(["A", "B"], [{ src: "A", dst: "Z" }]);
    expect(p.A?.x).toBe(0);
    expect(p.B?.x).toBe(0);
    expect(p.A?.y).not.toBe(p.B?.y);
  });
});

describe("groupLayout (no P&ID)", () => {
  const ids = [
    ...Array.from({ length: 23 }, (_, i) => `P1_T${i}`),
    "P2_A",
    "P2_B",
    "P3_X",
    "P4_Y",
  ];
  const pos = groupLayout(ids);

  it("groups tags by process prefix", () => {
    expect(processOf("P3_LCV01D")).toBe("P3");
    expect(processOf("weird")).toBe("?");
  });

  it("places every node once, wraps big processes into columns, and never overlaps", () => {
    expect(Object.keys(pos)).toHaveLength(ids.length);
    expect(new Set(Object.values(pos).map((p) => `${p.x},${p.y}`)).size).toBe(ids.length);
    const p1x = new Set(ids.filter((i) => i.startsWith("P1")).map((i) => pos[i]?.x));
    expect(p1x.size).toBe(3); // 23 nodes at 10 per column
  });

  it("keeps processes in separate, ordered blocks", () => {
    const maxP1 = Math.max(...ids.filter((i) => i.startsWith("P1")).map((i) => pos[i]?.x ?? 0));
    expect(pos.P2_A?.x ?? 0).toBeGreaterThan(maxP1 + 104); // clear of a node's width
    expect(pos.P3_X?.x ?? 0).toBeGreaterThan(pos.P2_A?.x ?? 0);
    expect(pos.P4_Y?.x ?? 0).toBeGreaterThan(pos.P3_X?.x ?? 0);
  });

  it("is vertically centred and compact", () => {
    const ys = ids.filter((i) => i.startsWith("P1")).map((i) => pos[i]?.y ?? 0);
    expect(Math.max(...ys)).toBeLessThan(400);
    expect(Math.min(...ys)).toBeGreaterThan(-400);
  });
});
