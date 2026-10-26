import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Incident } from "../../lib/types";
import { OriginCard } from "./OriginCard";

/** Expert Panel Review (Frontend #3): the confidence gate only catches a fraction of wrong-Top-1
 *  cases (held-out: 2 of 8), so the card now shows the actual Top-1/Top-2 margin, not just the
 *  binary Ambiguous flag -- an operator can judge a narrow call even when the gate doesn't fire. */

function incident(origin: Incident["origin"], ambiguous = false): Incident {
  return {
    id: "inc_1",
    status: "open",
    detected_at: 0,
    origin,
    path: [],
    path_edges: [],
    explanation: "",
    action: "",
    mitre: "",
    mitre_name: "",
    baseline_alarms: [],
    ground_truth: null,
    ambiguous,
  };
}

const html = (inc: Incident): string =>
  renderToStaticMarkup(createElement(OriginCard, { incident: inc }));

describe("OriginCard confidence margin", () => {
  it("shows the Top-1/Top-2 margin, not just the raw Top-1 score", () => {
    const m = html(
      incident([
        { id: "LIT101", type: "sensor", confidence: 0.82 },
        { id: "PLC1", type: "controller", confidence: 0.4 },
      ]),
    );
    expect(m).toContain('data-testid="origin-margin"');
    expect(m).toContain("+42% margin"); // 0.82 - 0.40 = 0.42
  });

  it("omits the margin when there is no #2 candidate", () => {
    const m = html(incident([{ id: "LIT101", type: "sensor", confidence: 0.9 }]));
    expect(m).not.toContain('data-testid="origin-margin"');
  });

  it("does not render the margin on the Ambiguous path (a different layout entirely)", () => {
    const m = html(
      incident(
        [
          { id: "LIT101", type: "sensor", confidence: 0.35 },
          { id: "PLC1", type: "controller", confidence: 0.33 },
          { id: "MV101", type: "actuator", confidence: 0.32 },
        ],
        true,
      ),
    );
    expect(m).toContain('data-testid="ambiguous"');
    expect(m).not.toContain('data-testid="origin-margin"');
  });
});
