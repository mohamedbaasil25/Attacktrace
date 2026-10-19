import { expect, test } from "@playwright/test";

// Phase 14 C3: real Playwright recordings for the "stage fails, show a video" fallback path.
// Not part of the regular smoke suite -- run on demand: npx playwright test e2e/fallback-videos.spec.ts
// Needs the stack up (SIM) and, for the LIVE test, a reachable emulator with a trained LIVE model.
const KEY: Record<string, string> = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};

test.use({ video: "on" });

test.describe("fallback videos", () => {
  test("SIM: sensor_offset on LIT101 to Contained", async ({ page, request }) => {
    test.setTimeout(90_000);
    await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
    await request.post("/api/reset", { headers: KEY });
    await page.goto("/");
    await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();
    await page.waitForTimeout(30_000); // the documented demo settle time

    await page.getByRole("button", { name: "Launch" }).click();
    await expect(page.getByRole("status", { name: "Status Incident" })).toBeVisible({
      timeout: 15_000,
    });

    const isolate = page.getByRole("button", { name: /^Isolate/ });
    await expect(isolate).toBeVisible({ timeout: 15_000 });
    await isolate.click();
    await expect(page.getByText("Contained", { exact: true })).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(2_000); // let the Contained state hold on screen a moment
  });

  test("LIVE: sensor_offset on LIT101 to a ranked origin", async ({ page, request }) => {
    test.setTimeout(60_000);
    await request.post("/api/mode", { data: { mode: "live" }, headers: KEY });
    await page.goto("/");
    await expect(page.getByRole("status", { name: /^Status/ })).toBeVisible({ timeout: 15_000 });

    const r = await request.post("/api/attack", {
      data: { scenario: "sensor_offset", target: "LIT101", magnitude: -25.0 },
      headers: KEY,
    });
    expect(r.ok()).toBeTruthy();

    const incident = page.getByRole("region", { name: "Incident" });
    const origin = incident.locator(
      '[data-testid="origin-id"]:text-is("LIT101"), [data-testid="candidate-LIT101"]',
    );
    await expect(origin).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(2_000);
  });
});
