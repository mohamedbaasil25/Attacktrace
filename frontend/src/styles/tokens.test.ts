import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");

// Phase 15 token palette (docs/UI_SPEC.md). The pre-Phase-15 back-compat aliases (--bg,
// --surface, --border, --text, --muted, --radius, --space) have been fully migrated off and
// removed from tokens.css -- every component now reads the canonical names below directly.
const spec: Record<string, string> = {
  "bg-0": "#080b10",
  "bg-1": "#0d1219",
  "bg-2": "#131a24",
  "bg-3": "#1a2330",
  "line-1": "#1b2431",
  "line-2": "#263244",
  focus: "#4c8dff",
  "text-1": "#e8eef5",
  "text-2": "#a5b1c0",
  "text-3": "#828ea0", // lightened from the source prompt's #6f7c8e: that value failed WCAG
  // 4.5:1 for body text on bg-1/bg-2/bg-3 (confirmed by scripts/check_contrast.ts); neutral
  // (status indicator, needs only 3:1) keeps the original #6f7c8e.
  accent: "#4c8dff",
  normal: "#2ea97d",
  suspect: "#e3b341",
  affected: "#f0883e",
  origin: "#ff5c57",
  info: "#4c8dff",
  neutral: "#6f7c8e",
  "r-sm": "6px",
  "r-md": "10px",
  "r-lg": "14px",
};

describe("design tokens", () => {
  it.each(Object.entries(spec))("--%s = %s", (name, hex) => {
    expect(css).toContain(`--${name}: ${hex};`);
  });

  it.each(["bg", "surface", "border", "text", "muted", "radius", "space"])(
    "no longer defines the pre-Phase-15 --%s alias",
    (name) => {
      expect(css).not.toMatch(new RegExp(`--${name}:\\s`));
    },
  );

  it("respects reduced motion", () => {
    expect(css).toContain("prefers-reduced-motion");
  });

  it("has an accent-soft tint for highlighted surfaces", () => {
    expect(css).toContain("--accent-soft: rgba(76, 141, 255, 0.06);");
  });
});
