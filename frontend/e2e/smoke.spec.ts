import { expect, test, type Page } from "@playwright/test";

// Direct API calls (setup only) send the demo key when AT_API_KEY is set; the UI sends its own.
const KEY: Record<string, string> = process.env.AT_API_KEY ? { "x-api-key": process.env.AT_API_KEY } : {};

/** Collects anything the page logs as an error or throws. */
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("launch sensor_offset on LIT101 and the incident panel names LIT101", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const errors = watchErrors(page);
  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await request.post("/api/reset", { headers: KEY }); // start from a clean plant, no old incident

  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();

  // The console defaults to sensor_offset on LIT101.
  await page.getByRole("button", { name: "Launch" }).click();

  const incident = page.getByRole("region", { name: "Incident" });
  // One confident origin, or (when the top two are too close) LIT101 among the equal top 3.
  const origin = incident.locator(
    '[data-testid="origin-id"]:text-is("LIT101"), [data-testid="candidate-LIT101"]',
  );
  await expect(origin).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("status", { name: "Status Incident" })).toBeVisible();

  // Once the incident window has filled, the answer must still be LIT101. The status chip reads
  // "Incident" once open and non-ambiguous, or "Ambiguous" when the top two are too close
  // (Phase 15: the raw "open"/"localizing" status word was replaced by a human label chip).
  await expect(incident.getByTestId("incident-status")).toHaveText(/^(Incident|Ambiguous)$/, {
    timeout: 30_000,
  });
  await expect(origin).toBeVisible();
  await expect(incident.getByText("T0856")).toBeVisible();

  expect(errors).toEqual([]);
});

test("graph, split and metrics views render without console errors", async ({ page, request }) => {
  const errors = watchErrors(page);
  // The real-data cards show whenever metrics.json carries HAI results (a shipped copy does, even
  // without the data files), so key the check on the metrics themselves.
  const metrics = (await (await request.get("/api/metrics")).json()) as { hai?: unknown };
  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await request.post("/api/reset", { headers: KEY }); // the previous test leaves an attack running
  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();

  await page.getByRole("button", { name: "Graph" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(9);

  await page.getByRole("button", { name: "Split view" }).click();
  await expect(page.getByRole("region", { name: "Baseline" })).toBeVisible();
  await expect(page.getByRole("region", { name: "AttackTrace" })).toBeVisible();

  await page.goto("/metrics");
  await expect(page.getByRole("heading", { name: "Metrics" })).toBeVisible();
  await expect(page.getByText("Top-1", { exact: true })).toBeVisible();
  const hai = page.getByRole("region", { name: "HAI results" });
  if (metrics.hai) await expect(hai).toBeVisible();
  else await expect(hai).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("HAI replay: the dataset's tags appear and its first attack raises an incident", async ({
  page,
  request,
}) => {
  test.setTimeout(240_000);
  const status = (await (await request.get("/api/status")).json()) as { hai_available: boolean };
  test.skip(!status.hai_available, "no HAI files in data/hai");
  const errors = watchErrors(page);
  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });

  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();
  await page.getByRole("button", { name: "hai", exact: true }).click();

  // A dataset replay has no twin and no attack console; the graph shows the dataset's tags.
  await expect(page.getByRole("button", { name: "Twin" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Restart" })).toBeVisible();
  await expect.poll(() => page.locator(".react-flow__node").count(), { timeout: 20_000 }).toBeGreaterThan(20);
  await expect(page.locator(".react-flow__node").first()).toContainText(/^P\d_/);

  // The replay starts five minutes before the first attack; the detector flags it within minutes.
  await expect(page.getByRole("status", { name: "Status Incident" })).toBeVisible({ timeout: 180_000 });
  const incident = page.getByRole("region", { name: "Incident" });
  await expect(incident.getByTestId("origin-id")).toHaveText(/^P\d_/);
  await expect(incident.getByText(/^T0\d{3}$/)).toHaveCount(0); // HAI carries no ATT&CK label

  await page.getByRole("button", { name: "sim", exact: true }).click(); // and back to the plant
  await expect(page.getByRole("button", { name: "Launch" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Isolate the top candidate: the incident ends Contained and the report downloads", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const errors = watchErrors(page);
  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });
  await request.post("/api/reset", { headers: KEY });

  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();
  await page.getByRole("button", { name: "Launch" }).click();

  const incident = page.getByRole("region", { name: "Incident" });
  await expect(incident.getByTestId("incident-status")).toHaveText(/^(Incident|Ambiguous)$/, {
    timeout: 40_000,
  });
  await expect(incident.getByTestId("breakdown-LIT101")).toBeVisible(); // score breakdown shown

  // Isolate is gated on an operator name (attributed, never anonymous).
  await page.getByRole("textbox", { name: "Operator name" }).fill("Playwright");
  await incident.getByRole("button", { name: /^Isolate / }).click();
  await expect(incident.getByTestId("isolate-state")).toContainText("Contained", { timeout: 40_000 });
  await expect(incident.getByTestId("isolate-state")).toContainText("by Playwright");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible({ timeout: 20_000 });

  const href = await incident.getByRole("link", { name: "Report" }).getAttribute("href");
  expect(href).toMatch(/\/api\/incidents\/inc_\d+\/report\.pdf$/);
  const pdf = await request.get(href ?? "");
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");

  expect(errors).toEqual([]);
});

test("a locked demo shows one line, not a stack trace", async ({ page }) => {
  // UI behaviour test: the server's 401/403 is simulated by intercepting the request.
  const errors = watchErrors(page);
  await page.route("**/api/attack", (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"API key required"}' }),
  );
  await page.goto("/");
  await expect(page.getByRole("status", { name: /Status/ })).toBeVisible();
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page.getByRole("alert").getByText("Demo locked")).toBeVisible();
  expect(errors.filter((e) => !e.includes("401"))).toEqual([]); // the failed fetch itself is logged
});

test("LIVE: switch to the plant emulator and launch sensor_offset on LIT101", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const status = (await (await request.get("/api/status")).json()) as {
    live_available: boolean;
  };
  test.skip(!status.live_available, "no plant emulator reachable (make emulator)");
  const errors = watchErrors(page);
  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY });

  await page.goto("/");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible();
  await page.getByRole("button", { name: "live", exact: true }).click();
  await expect(page.getByRole("status", { name: "Source Live" })).toBeVisible({ timeout: 20_000 });

  const calibrating = (await (await request.get("/api/status")).json()) as {
    source?: { state?: string };
  };
  test.skip(
    calibrating.source?.state === "calibrating",
    "LIVE has no trained model yet (make live-train)",
  );

  await page.getByRole("button", { name: "Launch" }).click();
  const incident = page.getByRole("region", { name: "Incident" });
  const origin = incident.locator(
    '[data-testid="origin-id"]:text-is("LIT101"), [data-testid="candidate-LIT101"]',
  );
  await expect(origin).toBeVisible({ timeout: 40_000 });
  await expect(page.getByRole("status", { name: "Status Incident" })).toBeVisible();

  // Read-only: Isolate is disabled with the exact LIVE tooltip, nothing was written to the plant.
  await expect(incident.getByRole("button", { name: /^Isolate /, exact: false })).toBeDisabled();
  await expect(page.getByTitle("Read-only")).toBeVisible();

  await request.post("/api/mode", { data: { mode: "sim" }, headers: KEY }); // leave it as found
  expect(errors).toEqual([]);
});
