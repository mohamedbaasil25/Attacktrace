import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Direct API calls (setup only) send the demo key when AT_API_KEY is set; the UI sends its own.
const KEY: Record<string, string> = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};

/** Phase 15 Part E: automated WCAG 2 A/AA sweep (the @axe-core/playwright dependency approved in
 *  Part 0). Complements, not replaces, scripts/check_contrast.ts (that checks the token palette's
 *  literal values; axe checks what actually renders, including composited/opacity colours) and the
 *  manual keyboard/focus passes already done by hand for the twin, incident panel and consoles. */
async function sweep(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

test("idle dashboard has no WCAG 2 A/AA violations", async ({ page }) => {
  await page.request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await page.request.post("/api/reset", { headers: KEY });
  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();
  await sweep(page);
});

test("an open incident has no WCAG 2 A/AA violations", async ({ page }) => {
  test.setTimeout(60_000);
  await page.request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await page.request.post("/api/reset", { headers: KEY });
  await page.goto("/");
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page.getByTestId("incident-status")).toBeVisible({ timeout: 30_000 });
  await sweep(page);
});

test("split view has no WCAG 2 A/AA violations", async ({ page }) => {
  await page.request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await page.request.post("/api/reset", { headers: KEY });
  await page.goto("/");
  await page.getByRole("button", { name: "Split view" }).click();
  await expect(page.getByRole("region", { name: "Split view" })).toBeVisible();
  await sweep(page);
});

test("process graph has no WCAG 2 A/AA violations", async ({ page }) => {
  await page.request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await page.request.post("/api/reset", { headers: KEY });
  await page.goto("/");
  await page.getByRole("button", { name: "Graph" }).click();
  await expect(page.getByRole("application")).toBeVisible();
  // The stage's 200ms crossfade (App.tsx's AnimatePresence) is still mid-fade right after the
  // node mounts "visible" -- axe would otherwise score the transient blended colour, not the
  // settled one.
  await page.waitForTimeout(300);
  await sweep(page);
});

test("metrics page has no WCAG 2 A/AA violations", async ({ page }) => {
  await page.goto("/metrics");
  await expect(page.getByRole("heading", { name: "Metrics" })).toBeVisible();
  await sweep(page);
});
