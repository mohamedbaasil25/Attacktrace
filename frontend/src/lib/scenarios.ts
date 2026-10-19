import type { NodeKind, Scenario, TopologyNode } from "./types";

export const SCENARIOS: readonly Scenario[] = [
  "sensor_freeze",
  "sensor_offset",
  "sensor_ramp",
  "actuator_force",
  "rogue_setpoint",
];

export const SCENARIO_LABEL: Record<Scenario, string> = {
  sensor_freeze: "Sensor freeze",
  sensor_offset: "Sensor offset",
  sensor_ramp: "Sensor ramp",
  actuator_force: "Actuator force",
  rogue_setpoint: "Rogue setpoint",
};

/** Which node kind each scenario may target (mirrors backend `VALID_TARGETS`). */
export const TARGET_KIND: Record<Scenario, NodeKind> = {
  sensor_freeze: "sensor",
  sensor_offset: "sensor",
  sensor_ramp: "sensor",
  actuator_force: "actuator",
  rogue_setpoint: "controller",
};

export function validTargets(scenario: Scenario, nodes: readonly TopologyNode[]): TopologyNode[] {
  return nodes.filter((n) => n.type === TARGET_KIND[scenario]);
}

export type MagnitudeInput =
  | { kind: "none" }
  | { kind: "number"; unit: string; step: number; min: number; max: number; value: number }
  | { kind: "toggle"; off: string; on: string; value: 0 | 1 };

/** Magnitude control + sensible default for a scenario/target pair. */
export function magnitudeFor(scenario: Scenario, target: TopologyNode | undefined): MagnitudeInput {
  const span = target ? target.hi - target.lo : 100;
  const unit = target?.unit ?? "";
  switch (scenario) {
    case "sensor_freeze":
      return { kind: "none" };
    case "sensor_offset": {
      const step = niceStep(span);
      return { kind: "number", unit, step, min: -span, max: span, value: -round(0.25 * span, step) };
    }
    case "sensor_ramp": {
      const step = niceStep(span);
      return { kind: "number", unit, step, min: -span, max: span, value: round(0.3 * span, step) };
    }
    case "actuator_force":
      return target?.id === "MV101"
        ? { kind: "toggle", off: "Closed", on: "Open", value: 1 }
        : { kind: "toggle", off: "Off", on: "On", value: 0 };
    case "rogue_setpoint":
      return { kind: "number", unit: "%", step: 5, min: -45, max: 45, value: 25 };
  }
}

function niceStep(span: number): number {
  return span >= 50 ? 1 : span >= 5 ? 0.5 : 0.05;
}

function round(x: number, step: number): number {
  return Math.round(x / step) * step;
}
