import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Incident, OriginCandidate } from "../../lib/types";
import { IncidentTriageList } from "./IncidentTriageList";

function inc(
  id: string,
  confidence: number,
  ambiguous: boolean,
  detectedAt: number,
): Incident {
  const origin: OriginCandidate[] = [{ id: "LIT101", type: "sensor", confidence }];
  return {
    id,
    status: "open",
    detected_at: detectedAt,
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

const html = (incidents: Incident[]): string =>
  renderToStaticMarkup(
    createElement(IncidentTriageList, { incidents, now: 100, onSelect: () => undefined }),
  );

describe("IncidentTriageList", () => {
  it("renders one row per incident, in the array's order (trusts the backend's sort)", () => {
    const m = html([inc("inc_amb", 0.4, true, 50), inc("inc_b", 0.9, false, 10)]);
    expect(m.match(/data-testid="incident-triage-row"/g)).toHaveLength(2);
    expect(m).toContain("Ambiguous");
    expect(m.indexOf("Ambiguous")).toBeLessThan(m.indexOf("90%"));
  });

  it("shows the origin id and confidence for each row", () => {
    const m = html([inc("inc_a", 0.73, false, 10)]);
    expect(m).toContain("LIT101");
    expect(m).toContain("73%");
  });

  it("renders nothing when there are no incidents", () => {
    const m = html([]);
    expect(m.match(/data-testid="incident-triage-row"/g)).toBeNull();
  });
});
