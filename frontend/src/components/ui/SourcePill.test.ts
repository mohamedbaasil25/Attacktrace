import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SourceInfo } from "../../lib/types";
import { SourcePill } from "./SourcePill";

const base: SourceInfo = {
  mode: "live",
  connected: true,
  protocol: "modbus",
  state: "connected",
  latency_ms_p50: 38,
  latency_ms_p95: 60,
  samples_per_s: 20,
  dropped: 0,
  reason: null,
  progress: null,
};

const html = (s: SourceInfo): string => renderToStaticMarkup(createElement(SourcePill, { source: s }));

describe("SourcePill", () => {
  it("shows Live with rounded latency and samples/s when connected", () => {
    const m = html(base);
    expect(m).toContain("Live");
    expect(m).toContain("38 ms");
    expect(m).toContain("20/s");
    expect(m).toContain('role="status"');
  });

  it("never carries latency detail once not connected (icon + label only)", () => {
    for (const state of ["stale", "connecting", "down", "calibrating"] as const) {
      const m = html({ ...base, state, connected: state === "stale" });
      expect(m).not.toContain(" ms ·");
      expect(m).not.toContain("/s</");
    }
  });

  it("labels every state distinctly (never colour alone)", () => {
    expect(html({ ...base, state: "stale" })).toContain("Stale");
    expect(html({ ...base, state: "connecting" })).toContain("Connecting");
    expect(html({ ...base, state: "down" })).toContain("Down");
    expect(html({ ...base, state: "calibrating" })).toContain("Calibrating");
  });

  it("puts the reason in the tooltip when given", () => {
    const m = html({ ...base, state: "down", connected: false, reason: "connection refused" });
    expect(m).toContain('title="connection refused"');
  });
});
