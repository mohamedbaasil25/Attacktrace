import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { NodeState } from "../../lib/types";
import { NodeBadge } from "./NodeBadge";

function node(overrides: Partial<NodeState> = {}): NodeState {
  return { id: "LIT101", value: 50, truth: null, score: 0.5, status: "normal", ...overrides };
}

const html = (n: NodeState, ageMs?: number | null): string =>
  renderToStaticMarkup(createElement(NodeBadge, { node: n, at: { x: 0, y: 0 }, ageMs }));

describe("NodeBadge quality marker", () => {
  it("draws nothing extra when quality is good or absent", () => {
    expect(html(node({ quality: "good" }))).not.toContain("Stale");
    expect(html(node())).not.toContain("Stale"); // SIM/HAI: no quality field at all
  });

  it("shows an icon and a tooltip with the age for a bad quality", () => {
    const m = html(node({ quality: "stale" }), 1500);
    expect(m).toContain("Stale · 1.5 s old");
  });

  it("gives every problem quality its own marker", () => {
    for (const q of ["stale", "missing", "out_of_range", "frozen"] as const) {
      expect(html(node({ quality: q }), 10)).toContain("svg");
    }
  });
});
