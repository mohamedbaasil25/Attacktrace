// Phase 15 §3.1: WCAG contrast check for every text/surface and status/surface pair the token
// set defines. Reads the literal hex values straight out of tokens.css (single source of truth,
// no duplicated palette here) and fails the process if any pair is below the bar: 4.5:1 for body
// text, 3:1 for large text / icons and status indicators.
//
//   npm run check:contrast
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const TOKENS_PATH = fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url));

function parseTokens(css: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of css.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});/g)) {
    out[m[1]] = m[2];
  }
  return out;
}

/** `rgba(r, g, b, a)` tokens (e.g. --accent-soft): translucent fills used as a Chip/row
 *  background, not caught by the plain-hex parser above. */
function parseRgbaTokens(css: string): Record<string, { rgb: [number, number, number]; a: number }> {
  const out: Record<string, { rgb: [number, number, number]; a: number }> = {};
  for (const m of css.matchAll(/--([a-z0-9-]+):\s*rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\);/g)) {
    out[m[1]] = { rgb: [Number(m[2]), Number(m[3]), Number(m[4])], a: Number(m[5]) };
  }
  return out;
}

function srgbToLinear(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function relativeLuminanceRgb([r, g, b]: readonly [number, number, number]): number {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

function contrastRatioRgb(a: readonly [number, number, number], b: readonly [number, number, number]): number {
  const la = relativeLuminanceRgb(a);
  const lb = relativeLuminanceRgb(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

function contrastRatio(hexA: string, hexB: string): number {
  return contrastRatioRgb(hexToRgb(hexA), hexToRgb(hexB));
}

/** Flattens a translucent fg (e.g. --accent-soft at 14% alpha) onto an opaque bg, as the browser
 *  actually paints it -- the composited result, not the fill's own colour, is what gets measured
 *  against foreground text sitting on top of it. */
function compositeOverHex(
  fg: { rgb: readonly [number, number, number]; a: number },
  bgHex: string,
): [number, number, number] {
  const bg = hexToRgb(bgHex);
  return fg.rgb.map((c, i) => c * fg.a + bg[i] * (1 - fg.a)) as [number, number, number];
}

const tokens = parseTokens(readFileSync(TOKENS_PATH, "utf8"));
const rgbaTokens = parseRgbaTokens(readFileSync(TOKENS_PATH, "utf8"));
const surfaces = ["bg-0", "bg-1", "bg-2", "bg-3"];
const text = ["text-1", "text-2", "text-3"];
const status = ["normal", "suspect", "affected", "origin", "info", "neutral"];
// Chip tone="accent" (the only tone with a translucent fill) renders accent text on top of its
// own accent-soft background -- a composite axe caught that the plain hex-pair loop above can't
// (Phase 15 Part E: found via the @axe-core/playwright sweep, not this script).
const translucentFills = ["accent-soft"];

type Row = { pair: string; ratio: number; need: number; ok: boolean };
const rows: Row[] = [];

for (const s of surfaces) {
  for (const t of text) {
    const ratio = contrastRatio(tokens[t], tokens[s]);
    const need = 4.5; // body text <=18px
    rows.push({ pair: `${t} on ${s}`, ratio, need, ok: ratio >= need });
  }
  for (const st of status) {
    const ratio = contrastRatio(tokens[st], tokens[s]);
    const need = 3.0; // status indicators are icons/large-text, not body copy
    rows.push({ pair: `${st} on ${s}`, ratio, need, ok: ratio >= need });
  }
  for (const fillName of translucentFills) {
    const composite = compositeOverHex(rgbaTokens[fillName], tokens[s]);
    const ratio = contrastRatioRgb(hexToRgb(tokens.accent), composite);
    const need = 4.5; // caption-size chip text
    rows.push({ pair: `accent on ${fillName}-over-${s}`, ratio, need, ok: ratio >= need });
  }
}

const width = Math.max(...rows.map((r) => r.pair.length));
for (const r of rows) {
  const line = `${r.ok ? "PASS" : "FAIL"}  ${r.pair.padEnd(width)}  ${r.ratio.toFixed(2)}:1  (need ${r.need}:1)`;
  console.log(line);
}

const failures = rows.filter((r) => !r.ok);
console.log(`\n${rows.length - failures.length}/${rows.length} pairs pass`);
if (failures.length > 0) {
  console.error(`${failures.length} pair(s) below the WCAG bar -- adjust tokens.css`);
  process.exit(1);
}
