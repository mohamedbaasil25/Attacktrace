// Phase 13 Part E: LIVE-mode screenshots. Needs the stack AND the plant emulator running
// (`make emulator`), and a trained LIVE model (`make live-train`) so the engine is not stuck
// `calibrating`. Sends AT_API_KEY on write calls when set.
//
//   AT_API_KEY=... node submission/tools/capture_live_screenshots.mjs [outDir]
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const OUT = process.argv[2] ?? "submission/screenshots";
const KEY = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};
const SIZES = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const log = [];
const errors = [];

async function shot(page, name, size) {
  const file = join(OUT, `${name}_${size.width}x${size.height}.png`);
  await page.screenshot({ path: file });
  log.push({ file });
  console.log(`saved ${file}`);
}

async function liveViews(browser, size) {
  const ctx = await browser.newContext({ viewport: size });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`live ${size.width}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`live ${size.width}: ${e.message}`));
  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  await page.getByRole("button", { name: "live", exact: true }).click();
  await page.getByRole("status", { name: "Source Live" }).waitFor({ timeout: 20_000 });
  await sleep(1500);
  await shot(page, "11-live-connected", size);

  await page.getByRole("button", { name: "Launch" }).click();
  await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 40_000 });
  await sleep(1500);
  await shot(page, "12-live-incident", size);

  await ctx.close();
}

const browser = await chromium.launch();
for (const size of SIZES) await liveViews(browser, size);
await browser.close();

writeFileSync(join(OUT, "capture_log_live.json"), JSON.stringify({ shots: log, console_errors: errors }, null, 1));
console.log(`\n${log.length} screenshots, ${errors.length} console errors`);
if (errors.length) console.log(errors.join("\n"));
