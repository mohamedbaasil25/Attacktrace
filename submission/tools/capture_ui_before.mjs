// Phase 15 Part 0 audit: fast "before" screenshots of the current UI (stack must be running on
// :5173/:8000). Not the final before/after set (that's Part F, full 4-resolution matrix) -- this
// is a quick representative sweep for the redesign audit.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const OUT = process.argv[2] ?? "submission/evidence/ui_before";
const SIZE = { width: 1440, height: 900 };
const KEY = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

async function shot(page, name) {
  const file = join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  console.log(`saved ${file}`);
}

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: SIZE });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await ctx.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
  await ctx.request.post(`${BASE}/api/reset`, { headers: KEY });
  await page.goto(BASE);
  await page.getByRole("status", { name: "Status Normal" }).waitFor();
  await sleep(2000);
  await shot(page, "01-idle");

  await page.getByRole("button", { name: "Launch" }).click();
  await sleep(1500);
  await shot(page, "02-attack-running");

  await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 15000 });
  await sleep(500);
  await shot(page, "03-incident-localizing");

  await page.getByText("open", { exact: true }).waitFor({ timeout: 30000 });
  await sleep(500);
  await shot(page, "04-incident-open");

  await page.getByRole("button", { name: "Split view" }).click();
  await sleep(500);
  await shot(page, "05-split");

  await page.getByRole("button", { name: "Graph", exact: true }).click();
  await sleep(500);
  await shot(page, "06-graph");

  const isolate = page.getByRole("button", { name: /^Isolate/ });
  if (await isolate.isVisible()) {
    await isolate.click();
    try {
      await page.getByText("Contained", { exact: true }).waitFor({ timeout: 30000 });
      await sleep(500);
      await shot(page, "07-contained");
    } catch {
      console.log("isolate did not contain in time, skipping 07-contained");
    }
  }

  await page.goto(`${BASE}/metrics`);
  await sleep(1500);
  await shot(page, "08-metrics");

  console.log(errors.length ? `console errors:\n${errors.join("\n")}` : "no console errors");
  await browser.close();
}

main();
