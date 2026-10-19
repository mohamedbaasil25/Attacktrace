import { describe, expect, it } from "vitest";
import {
  incidentStartIndex,
  indexToX,
  markers,
  nodeSeries,
  seriesPath,
  stepCursor,
  timelineRows,
  xToIndex,
} from "./replay";
import type { Incident, LiveMessage } from "./types";

const inc = (id: string, startedAt?: number): Incident => ({
  id,
  status: "open",
  detected_at: 0,
  origin: [],
  path: [],
  path_edges: [],
  explanation: "",
  action: "",
  mitre: "T0856",
  mitre_name: "",
  baseline_alarms: [],
  ground_truth: startedAt === undefined
    ? null
    : { attack_id: "atk_001", scenario: "sensor_offset", target: "LIT101", started_at: startedAt, mitre: "T0856" },
});

const msg = (t: number, incident: Incident | null = null, value = t): LiveMessage => ({
  t,
  mode: "sim",
  nodes: [{ id: "LIT101", value, truth: value + 1, score: 0, status: "normal" }],
  alert: null,
  incident,
  incidents: incident ? [incident] : [],
  impact: null,
});

describe("stepCursor", () => {
  it("advances, then returns to live at the newest sample", () => {
    expect(stepCursor(3, 10)).toBe(4);
    expect(stepCursor(9, 10)).toBeNull();
    expect(stepCursor(null, 10)).toBeNull();
  });
});

describe("incidentStartIndex", () => {
  it("finds where the newest incident first appears", () => {
    const buf = [msg(0), msg(1), msg(2, inc("inc_001")), msg(3, inc("inc_001")), msg(4)];
    expect(incidentStartIndex(buf)).toBe(2);
    expect(incidentStartIndex([msg(0)])).toBeNull();
  });

  it("prefers the newest incident when there are several", () => {
    const buf = [msg(0, inc("inc_001")), msg(1), msg(2, inc("inc_002"))];
    expect(incidentStartIndex(buf)).toBe(2);
  });
});

describe("timeline axis", () => {
  it("pins the oldest sample to the left edge and round-trips", () => {
    const cap = 600;
    expect(indexToX(0, 100, cap, 599)).toBeCloseTo(0);
    expect(indexToX(99, 100, cap, 599)).toBeCloseTo(99);
    expect(indexToX(599, 600, cap, 599)).toBeCloseTo(599);
    for (const i of [0, 10, 57, 99]) {
      expect(xToIndex(indexToX(i, 100, cap, 599), 100, cap, 599)).toBe(i);
    }
  });

  it("clamps clicks outside the data", () => {
    expect(xToIndex(0, 100, 600, 599)).toBe(0);
    expect(xToIndex(10_000, 100, 600, 599)).toBe(99);
  });
});

describe("seriesPath", () => {
  it("scales values into the box with y flipped", () => {
    expect(seriesPath([0, 10], 2, 100, 20, 0, 10)).toBe("M0.0 20.0 L100.0 0.0");
    expect(seriesPath([5, 5], 2, 100, 20, 5, 5)).toContain("M0.0 20.0");
  });
});

describe("markers", () => {
  it("marks detection once per incident and attack launch by timestamp", () => {
    const buf = [msg(0), msg(1), msg(2), msg(3, inc("inc_001", 1)), msg(4, inc("inc_001", 1))];
    expect(markers(buf)).toEqual([
      { index: 3, kind: "detected", label: "inc_001 detected" },
      { index: 1, kind: "attack", label: "atk_001 launched" },
    ]);
    expect(markers([msg(0)])).toEqual([]);
  });
});

describe("nodeSeries", () => {
  it("collects reported and truth values", () => {
    const s = nodeSeries([msg(1), msg(2)], "LIT101");
    expect(s.reported).toEqual([1, 2]);
    expect(s.truth).toEqual([2, 3]);
    expect(nodeSeries([msg(1)], "NOPE").reported).toEqual([]);
  });
});

describe("timelineRows", () => {
  it("uses the four SIM sensors when they are all present", () => {
    const sim = ["LIT101", "MV101", "P101", "FIT201", "PIT301", "LIT301", "P301", "PLC1", "PLC2"];
    expect(timelineRows(sim)).toEqual(["LIT101", "FIT201", "PIT301", "LIT301"]);
  });

  it("prefers HAI level/flow/pressure tags and pads from the node list", () => {
    const hai = ["P1_B2004", "P1_FT01", "P1_LIT01", "P1_PIT01", "P3_LT01", "P4_ST_PS"];
    expect(timelineRows(hai)).toEqual(["P1_LIT01", "P1_FT01", "P1_PIT01", "P3_LT01"]);
    expect(timelineRows(["P1_FT01", "P1_B2004", "P2_X"])).toEqual(["P1_FT01", "P1_B2004", "P2_X"]);
    expect(timelineRows([])).toEqual([]);
  });
});
