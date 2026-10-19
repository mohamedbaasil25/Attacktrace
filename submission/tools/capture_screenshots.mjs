// Captures the submission screenshots with Playwright (the stack must be running on :5173/:8000).
//
//   node submission/tools/capture_screenshots.mjs [outDir]
//
// Per viewport (1440x900 and 1280x800): idle, attack in progress, incident localized, split view,
// graph view, incident resolved (the attack ends, the incident closes), and /metrics. At 1440x900
// it also records a HAI incident when HAI data is present. Sends AT_API_KEY on write calls. Console errors are collected and printed.
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const OUT = process.argv[2] ?? "submission/screenshots";
const SIZES = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
];
const KEY = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const log = [];
const errors = [];

async function shot(page, name, size) {
  const file = join(OUT, `${name}_${size.width}x${size.height}.png`);
  await page.screenshot({ path: file });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight,
  );
  log.push({ file, overflow });
  console.log(`saved ${file}${overflow ? "  (OVERFLOW)" : ""}`);
}

async function simViews(browser, size) {
  const ctx = await browser.newContext({ viewport: size });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`${size.width}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`${size.width}: ${e.message}`));
  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await ctx.request.post(`${BASE}/api/reset`, { headers: KEY });

  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  await sleep(120_000); // the timeline axis is 5 minutes: give the sparklines a visible stretch of data
  await shot(page, "01-idle", size);

  await page.getByRole("button", { name: "Launch" }).click(); // sensor_offset on LIT101 (defaults)
  await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 40_000 });
  await sleep(1500);
  await shot(page, "02-attack-in-progress", size);

  const incident = page.getByRole("region", { name: "Incident" });
  await incident.getByText("open", { exact: true }).waitFor({ timeout: 40_000 });
  await sleep(1000);
  await shot(page, "03-incident-localized", size);

  await page.getByRole("button", { name: "Split view" }).click();
  await sleep(2000); // the baseline alarms fade in one by one
  await shot(page, "04-split-view", size);
  await page.getByRole("button", { name: "Split view" }).click();

  await page.getByRole("button", { name: "Graph" }).click();
  await sleep(2500);
  await shot(page, "05-graph-view", size);
  await page.getByRole("button", { name: "Twin" }).click();

  // Isolate the top candidate: the incident reads Contained once the backend declares it.
  await incident.getByRole("button", { name: /^Isolate / }).click();
  await incident.getByTestId("isolate-state").getByText("Contained").waitFor({ timeout: 60_000 });
  await sleep(1000);
  await shot(page, "09-contained", size);
  // The contained incident leaves the feed after a few seconds; then the pill is Normal again.
  await page.getByRole("status", { name: "Status Normal" }).waitFor({ timeout: 120_000 });
  await sleep(1500);
  await shot(page, "06-incident-resolved", size);

  await page.goto(`${BASE}/metrics`);
  await page.getByRole("heading", { name: "Metrics" }).waitFor();
  await page.getByText("Top-1", { exact: true }).waitFor();
  await sleep(1500); // chart animation
  await shot(page, "07-metrics", size);
  await ctx.close();
}

/** Tries attacks until the live detector flags an incident as ambiguous (top two too close). */
async function ambiguousShot(browser, size) {
  const ctx = await browser.newContext({ viewport: size });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`amb ${size.width}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`amb ${size.width}: ${e.message}`));
  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.goto(BASE);
  const tries = [
    ["sensor_offset", "LIT301", -25], ["sensor_offset", "PIT301", 0.5], ["sensor_offset", "FIT201", 2],
    ["sensor_freeze", "LIT101", 0], ["rogue_setpoint", "PLC1", 25], ["sensor_offset", "LIT101", -25],
    ["sensor_ramp", "LIT301", 30], ["sensor_freeze", "PIT301", 0], ["rogue_setpoint", "PLC2", -25],
    ["sensor_offset", "LIT301", 25], ["sensor_freeze", "FIT201", 0], ["sensor_offset", "LIT101", 25],
  ];
  for (const [scenario, target, magnitude] of tries) {
    await ctx.request.post(`${BASE}/api/reset`, { headers: KEY });
    await sleep(25_000); // warm-up and a settled detector
    await ctx.request.post(`${BASE}/api/attack`, { data: { scenario, target, magnitude }, headers: KEY });
    for (let i = 0; i < 40; i++) {
      await sleep(1000);
      const inc = (await (await ctx.request.get(`${BASE}/api/incidents`)).json())[0];
      if (inc && inc.status === "open" && inc.ambiguous) {
        await page.getByTestId("ambiguous").waitFor({ timeout: 10_000 });
        await sleep(800);
        await shot(page, "10-ambiguous", size);
        log.push({ ambiguous_found: `${scenario} ${target} ${magnitude}`, size: size.width });
        await ctx.close();
        return;
      }
      if (inc && inc.status === "open") break; // open and confident: try the next attack
    }
  }
  console.log(`no ambiguous incident found at ${size.width}`);
  log.push({ ambiguous_found: null, size: size.width });
  await ctx.close();
}

async function haiIncident(browser, size) {
  const ctx = await browser.newContext({ viewport: size });
  const status = await (await ctx.request.get(`${BASE}/api/status`)).json();
  if (!status.hai_available) {
    console.log("no HAI data: skipping the HAI screenshot");
    await ctx.close();
    return;
  }
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`hai: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`hai: ${e.message}`));
  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "hai" }, headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 200_000 });
  await sleep(3_000); // the window fills in ~1 s at x10; the replay closes incidents quickly
  await shot(page, "08-hai-incident", size);
  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await ctx.close();
}

const browser = await chromium.launch();
for (const size of SIZES) await simViews(browser, size);
for (const size of SIZES) await ambiguousShot(browser, size);
await haiIncident(browser, SIZES[0]);
await browser.close();

writeFileSync(join(OUT, "capture_log.json"), JSON.stringify({ shots: log, console_errors: errors }, null, 1));
console.log(`\n${log.length} screenshots, ${log.filter((l) => l.overflow).length} with overflow, ${errors.length} console errors`);
if (errors.length) console.log(errors.join("\n"));
