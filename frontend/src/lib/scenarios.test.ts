import { describe, expect, it } from "vitest";
import { etaUrgency, formatEta, formatValue, isSpoofed } from "./format";
import { SCENARIOS, magnitudeFor, validTargets } from "./scenarios";
import type { TopologyNode } from "./types";

const node = (id: string, type: TopologyNode["type"], lo: number, hi: number, unit = ""): TopologyNode => ({
  id,
  type,
  label: id,
  unit,
  lo,
  hi,
});
const NODES = [
  node("LIT101", "sensor", 0, 100, "%"),
  node("FIT201", "sensor", 0, 12, "L/s"),
  node("PIT301", "sensor", 0, 2.5, "bar"),
  node("MV101", "actuator", 0, 1),
  node("P101", "actuator", 0, 1),
  node("PLC1", "controller", 0, 1),
];
const byId = (id: string) => NODES.find((n) => n.id === id);

describe("validTargets", () => {
  it("mirrors the backend rules for every scenario", () => {
    const ids = (s: (typeof SCENARIOS)[number]) => validTargets(s, NODES).map((n) => n.id);
    expect(ids("sensor_freeze")).toEqual(["LIT101", "FIT201", "PIT301"]);
    expect(ids("sensor_offset")).toEqual(ids("sensor_ramp"));
    expect(ids("actuator_force")).toEqual(["MV101", "P101"]);
    expect(ids("rogue_setpoint")).toEqual(["PLC1"]);
  });
});

describe("magnitudeFor", () => {
  it("scales sensor offsets to the target range and sign-flips the default", () => {
    const lit = magnitudeFor("sensor_offset", byId("LIT101"));
    const pit = magnitudeFor("sensor_offset", byId("PIT301"));
    expect(lit).toMatchObject({ kind: "number", unit: "%", value: -25 });
    expect(pit).toMatchObject({ kind: "number", unit: "bar" });
    expect(pit.kind === "number" && Math.abs(pit.value)).toBeCloseTo(0.65, 2);
  });

  it("gives ramps a positive drift, freeze nothing, actuators a toggle", () => {
    expect(magnitudeFor("sensor_ramp", byId("LIT101"))).toMatchObject({ kind: "number", value: 30 });
    expect(magnitudeFor("sensor_freeze", byId("LIT101"))).toEqual({ kind: "none" });
    expect(magnitudeFor("actuator_force", byId("P101"))).toMatchObject({ kind: "toggle", on: "On", value: 0 });
    expect(magnitudeFor("actuator_force", byId("MV101"))).toMatchObject({ kind: "toggle", on: "Open" });
  });

  it("keeps rogue setpoint deltas inside the plausible range", () => {
    const m = magnitudeFor("rogue_setpoint", byId("PLC1"));
    expect(m).toMatchObject({ kind: "number", unit: "%", min: -45, max: 45 });
  });
});

describe("format", () => {
  it("formats by node family", () => {
    expect(formatValue("LIT101", 62.44)).toBe("62.4%");
    expect(formatValue("FIT201", 5.123)).toBe("5.12 L/s");
    expect(formatValue("PIT301", 1.2)).toBe("1.20 bar");
    expect(formatValue("P101", 0.6)).toBe("60%");
  });

  it("formats HAI tags in raw units and still treats SIM actuators as fractions", () => {
    expect(formatValue("P1_FT01", 126.624)).toBe("126.6");
    expect(formatValue("P1_LIT01", 404.18)).toBe("404.2");
    expect(formatValue("P1_PIT01", 1.0719)).toBe("1.07");
    expect(formatValue("P4_ST_PS", 12345.6)).toBe("12346");
    expect(formatValue("P101", 0.6)).toBe("60%");
    expect(formatValue("PLC2", 0.5)).toBe("50%");
  });

  it("flags spoofed sensors only when reported differs from truth by >3% of range", () => {
    const lit = byId("LIT101");
    expect(isSpoofed(lit, 50, 51)).toBe(false);
    expect(isSpoofed(lit, 30, 52)).toBe(true);
    expect(isSpoofed(lit, 50, null)).toBe(false);
    expect(isSpoofed(byId("P101"), 0, 1)).toBe(false); // actuators are never "spoofed"
  });

  it("renders ETAs and urgency", () => {
    expect(formatEta(null)).toBe("–");
    expect(formatEta(42.4)).toBe("42 s");
    expect(formatEta(180)).toBe("3 m");
    expect(etaUrgency(null)).toBe(0);
    expect(etaUrgency(0)).toBe(1);
    expect(etaUrgency(150)).toBeCloseTo(0.5);
    expect(etaUrgency(900)).toBe(0);
  });
});
