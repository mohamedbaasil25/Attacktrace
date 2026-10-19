import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Incident, OriginCandidate } from "../../lib/types";
import { BreakdownBar } from "./BreakdownBar";
import { OriginCard } from "./OriginCard";

const w = { deviation: 0.6, onset: 0.2, causal: 0.2 };

function cand(id: string, confidence: number, b?: [number, number, number]): OriginCandidate {
  return {
    id,
    type: "sensor",
    confidence,
    breakdown: b ? { deviation: b[0], onset: b[1], causal: b[2] } : null,
    weights: b ? w : null,
  };
}

function incident(origin: OriginCandidate[], ambiguous: boolean): Incident {
  return {
    id: "inc_001",
    status: "open",
    detected_at: 0,
    origin,
    path: [],
    path_edges: [],
    explanation: "",
    action: "",
    mitre: "T0856",
    mitre_name: "",
    baseline_alarms: [],
    ground_truth: null,
    ambiguous,
  };
}

const three: OriginCandidate[] = [
  cand("LIT101", 0.5, [0.6, 0.2, 0.15]),
  cand("PLC1", 0.3, [0.5, 0.1, 0.1]),
  cand("MV101", 0.2, [0.3, 0.1, 0.1]),
];
const top = cand("LIT101", 0.5, [0.6, 0.2, 0.15]);
const html = (i: Incident): string => renderToStaticMarkup(createElement(OriginCard, { incident: i }));

describe("breakdown bar", () => {
  it("draws three segments whose widths are the contributions", () => {
    const m = renderToStaticMarkup(createElement(BreakdownBar, { c: top }));
    expect(m).toContain("width:60%");
    expect(m).toContain("width:20%");
    expect(m).toContain("width:15%");
    expect(m).toContain("deviation 0.60 (weight 0.60)"); // tooltip values
    expect(m).toContain("LIT101 score breakdown: deviation 0.60, onset 0.20, causal 0.15");
  });

  it("renders nothing without a breakdown (e.g. an older backend)", () => {
    expect(renderToStaticMarkup(createElement(BreakdownBar, { c: cand("X", 1) }))).toBe("");
  });

  it("clamps a contribution into the bar", () => {
    const m = renderToStaticMarkup(createElement(BreakdownBar, { c: cand("X", 1, [1.4, -0.2, 0]) }));
    expect(m).toContain("width:100%");
    expect(m).toContain("width:0%");
  });
});

describe("origin card", () => {
  it("shows one origin with a bar per candidate when not ambiguous (max three)", () => {
    const m = html(incident([...three, cand("PLC2", 0.1, [0.1, 0.1, 0.1])], false));
    expect(m).toContain('data-testid="origin-id"');
    expect(m).not.toContain("Ambiguous");
    expect(m.match(/data-testid="breakdown-/g)).toHaveLength(3);
    expect(m).not.toContain("PLC2");
  });

  it("shows the top three as equals, with the Ambiguous label, when flagged", () => {
    const m = html(incident(three, true));
    expect(m).toContain("Ambiguous");
    expect(m).toContain("Top 3");
    expect(m).not.toContain('data-testid="origin-id"');
    for (const id of ["LIT101", "PLC1", "MV101"]) expect(m).toContain(`data-testid="candidate-${id}"`);
    expect(m.match(/data-testid="breakdown-/g)).toHaveLength(3);
  });
});
