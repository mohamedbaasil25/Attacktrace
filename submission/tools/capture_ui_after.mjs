// Phase 15 Part F: the full before/after screenshot matrix -- 14 states x 4 resolutions (stack
// must be running on :5173/:8000; HAI needs data/hai/*, LIVE-no-signal needs no plant emulator
// running, which is also realistic -- the emulator isn't started in this environment).
//
// 13 of the 14 states are fast (<15s) and captured at all 4 resolutions. State 14
// (hai-incident) waits up to 3 minutes for the HAI replay to raise its first alert, so it is
// captured once at the primary resolution only (1440x900) -- doing that at 4 sizes would cost
// ~12 minutes of pure waiting for one screenshot's worth of extra information.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const OUT = process.argv[2] ?? "submission/evidence/ui_after";
const KEY = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const RESOLUTIONS = [
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "1440x900", width: 1440, height: 900 }, // primary
  { name: "1920x1080", width: 1920, height: 1080 },
];

async function shot(page, dir, name) {
  const file = join(dir, `${name}.png`);
  await page.screenshot({ path: file });
  return file;
}

/** The 13 fast states, run identically at every resolution. */
async function fastStates(page, dir, errors) {
  await page.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.request.post(`${BASE}/api/reset`, { headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  await sleep(1500);
  await shot(page, dir, "01-idle");

  await page.getByRole("button", { name: "Launch" }).click();
  await sleep(1200);
  await shot(page, dir, "02-attack-running");

  await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 15_000 });
  await sleep(400);
  await shot(page, dir, "03-incident-localizing");

  const incident = page.getByRole("region", { name: "Incident" });
  await incident.getByTestId("incident-status").waitFor({ timeout: 30_000 });
  await sleep(400);
  await shot(page, dir, "04-incident-open");

  // A focused node (Part C: click a node-score row -> a focus ring on the twin).
  const mv101Row = page.getByRole("button", { name: /MV101/ });
  if (await mv101Row.isVisible().catch(() => false)) {
    await mv101Row.click();
    await sleep(300);
    await shot(page, dir, "05-node-focus");
    await mv101Row.click(); // toggle back off, don't leave it focused for later states
  } else {
    await shot(page, dir, "05-node-focus"); // no visible row at this width -- same frame, documented
  }

  const reveal = page.getByText("Reveal", { exact: true });
  if (await reveal.isVisible().catch(() => false)) {
    await reveal.click();
    await sleep(200);
  }
  await shot(page, dir, "06-reveal");

  await page.getByRole("button", { name: "Split view" }).click();
  await sleep(500);
  await shot(page, dir, "07-split");

  await page.getByRole("button", { name: "Graph", exact: true }).click();
  await sleep(500);
  await shot(page, dir, "08-graph");

  const isolate = page.getByRole("button", { name: /^Isolate/ });
  if (await isolate.isVisible().catch(() => false)) {
    await isolate.click();
    try {
      await page.getByTestId("isolate-state").filter({ hasText: "Contained" }).waitFor({ timeout: 30_000 });
      await sleep(400);
      await shot(page, dir, "09-contained");
    } catch {
      console.log(`[${dir}] isolate did not contain in time, skipping 09-contained`);
    }
  }

  const about = page.getByRole("button", { name: "About AttackTrace" });
  await about.click();
  await sleep(200);
  await shot(page, dir, "10-about-popover");
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/metrics`);
  await sleep(1200);
  await shot(page, dir, "11-metrics");

  // HAI idle: dataset tags visible, no wait for an incident (that's state 14, primary-res only).
  await page.goto(BASE);
  await page.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.goto(BASE);
  await page.getByRole("button", { name: "hai", exact: true }).click();
  await page
    .locator(".react-flow__node")
    .first()
    .waitFor({ timeout: 20_000 })
    .catch(() => console.log(`[${dir}] HAI graph node did not render in time`));
  await sleep(600);
  await shot(page, dir, "12-hai-idle");

  // LIVE, no emulator running in this environment: the toggle itself is disabled with a
  // "connection refused" tooltip rather than switchable -- that disabled-with-reason state is
  // what a viewer actually sees here, so capture it instead of forcing a click that can't land.
  await page.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  const liveToggle = page.getByRole("button", { name: "live", exact: true });
  await liveToggle.hover();
  await sleep(300);
  await shot(page, dir, "13-live-unavailable");

  console.log(errors.length ? `[${dir}] console errors:\n${errors.join("\n")}` : `[${dir}] no console errors`);
}

/** State 14: an HAI incident actually raised. Slow (up to 3 min) -- primary resolution only. */
async function haiIncidentState(page, dir) {
  await page.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  await page.getByRole("button", { name: "hai", exact: true }).click();
  try {
    await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 180_000 });
    await sleep(500);
    await shot(page, dir, "14-hai-incident");
  } catch {
    console.log(`[${dir}] HAI did not raise an incident within 3 min, skipping 14-hai-incident`);
  }
}

async function main() {
  const browser = await chromium.launch();
  for (const res of RESOLUTIONS) {
    const dir = join(OUT, res.name);
    mkdirSync(dir, { recursive: true });
    const ctx = await browser.newContext({ viewport: { width: res.width, height: res.height } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));

    await fastStates(page, dir, errors);
    if (res.name === "1440x900") await haiIncidentState(page, dir);

    await ctx.close();
    console.log(`done: ${res.name}`);
  }
  await browser.close();
}

main();
