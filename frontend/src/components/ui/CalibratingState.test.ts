import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CalibratingState } from "./CalibratingState";

const html = (p: number | null): string =>
  renderToStaticMarkup(createElement(CalibratingState, { progress: p }));

describe("CalibratingState", () => {
  it("shows the ring and the label with a percentage", () => {
    const m = html(0.42);
    expect(m).toContain("Calibrating 42%");
    expect(m).toContain("<svg");
    expect(m).toContain('role="status"');
  });

  it("shows the label without a percentage when progress is unknown", () => {
    const m = html(null);
    expect(m).toContain(">Calibrating<");
    expect(m).not.toContain("%");
  });

  it("clamps an out-of-range progress value, ring and label alike", () => {
    expect(html(1.4)).toContain("Calibrating 100%");
    expect(html(-0.2)).toContain("Calibrating 0%");
  });
});
