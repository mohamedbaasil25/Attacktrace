import { describe, expect, it } from "vitest";
import { HISTORY_RANGES, historyPath } from "./history";
import type { HistorySample } from "./types";

function sample(t: number, value: number): HistorySample {
  return { t, value, score: 0, status: "normal" };
}

describe("historyPath", () => {
  it("returns an empty path for fewer than two samples", () => {
    expect(historyPath([], 100, 50)).toBe("");
    expect(historyPath([sample(0, 1)], 100, 50)).toBe("");
  });

  it("places the first and last sample at the path's x extremes", () => {
    const d = historyPath([sample(0, 1), sample(10, 2), sample(20, 3)], 1000, 100);
    expect(d.startsWith("M0.0")).toBe(true);
    expect(d).toContain("L1000.0");
  });

  it("places a constant series mid-height with no NaN", () => {
    const d = historyPath([sample(0, 5), sample(10, 5)], 1000, 100);
    expect(d).not.toContain("NaN");
  });

  it("maps higher values to a smaller y (SVG y grows downward)", () => {
    const d = historyPath([sample(0, 0), sample(10, 100)], 100, 100);
    const [, y0, y1] = d.match(/M[\d.]+ ([\d.]+) L[\d.]+ ([\d.]+)/) ?? [];
    expect(Number(y0)).toBeGreaterThan(Number(y1));
  });
});

describe("HISTORY_RANGES", () => {
  it("is ordered shortest to longest", () => {
    const seconds = HISTORY_RANGES.map((r) => r.seconds);
    expect(seconds).toEqual([...seconds].sort((a, b) => a - b));
  });
});
