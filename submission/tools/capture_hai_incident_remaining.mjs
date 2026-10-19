// Phase 15 Part F follow-up: the 14th state (an HAI incident actually raised, up to 3 min wait)
// was captured at the primary resolution only in the main sweep. This fills in the other 3.
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
  { name: "1920x1080", width: 1920, height: 1080 },
];

async function main() {
  const browser = await chromium.launch();
  for (const res of RESOLUTIONS) {
    const ctx = await browser.newContext({ viewport: { width: res.width, height: res.height } });
    const page = await ctx.newPage();
    await page.request.post(`${BASE}/api/mode`, { data: { mode: "sim" }, headers: KEY });
    await page.goto(BASE);
    await page.getByRole("status", { name: "Status Normal" }).waitFor();
    await page.getByRole("button", { name: "hai", exact: true }).click();
    try {
      await page.getByRole("status", { name: "Status Incident" }).waitFor({ timeout: 180_000 });
      await sleep(500);
      await page.screenshot({ path: join(OUT, res.name, "14-hai-incident.png") });
      console.log(`[${res.name}] saved 14-hai-incident.png`);
    } catch {
      console.log(`[${res.name}] HAI did not raise an incident within 3 min, skipping`);
    }
    await ctx.close();
  }
  await browser.close();
}

main();
