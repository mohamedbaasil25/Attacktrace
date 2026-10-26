import { expect, test, type Page } from "@playwright/test";

/** Phase 4: end-to-end coverage of the Production Transition Roadmap's real-auth flow (Phase 1)
 * against a DEDICATED auth-enabled backend (`scripts/dev-e2e-auth-backend.ps1`, port 8010) with
 * its own incidents database -- never the same server `smoke.spec.ts` runs against, which
 * deliberately has no AT_AUTH_SECRET set and relies on the Operator-name fallback instead. Run
 * with: `npx playwright test e2e/auth.spec.ts` while that backend and a frontend dev server
 * proxying to it (`VITE_API_PROXY=http://localhost:8010 npm run dev -- --port 5175`) are both up.
 *
 * Credentials below are test-only, provisioned in `scripts/dev-e2e-auth-backend.ps1`'s
 * AT_OPERATORS roster; they exist nowhere else. */
const OPERATOR = { username: "opuser", password: "op-pass-123" };
const ANALYST = { username: "anuser", password: "an-pass-123" };

// This file's own dedicated stack (see the module docstring above), independent of
// playwright.config.ts's default baseURL that the rest of e2e/ targets.
test.use({ baseURL: process.env.E2E_AUTH_BASE_URL ?? "http://localhost:5175" });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function openLogin(page: Page) {
  await page.getByRole("button", { name: "Log in", exact: true }).click();
}

async function login(page: Page, user: { username: string; password: string }) {
  await openLogin(page);
  await page.getByRole("textbox", { name: "Username" }).fill(user.username);
  await page.getByRole("textbox", { name: "Password" }).fill(user.password);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
}

// Phase 5.3: /api/mode and /api/reset also require a real operator login once AT_AUTH_SECRET is
// configured (require_operator_when_configured) -- without a token these calls 401 and
// Playwright's `request` fixture does not throw on a non-2xx status, so a silent no-op here would
// leave stale state (a still-running attack, a leftover incident) bleeding into the next test
// instead of raising. Logged in ONCE for the whole file (not per test): the login endpoint has its
// own rate limit (10/min, same server every test in this file shares), and this file's own login
// tests add more login attempts on top -- re-authenticating in every `beforeEach` pushed total
// login volume over that limit. The token is valid for hours, so one is plenty for setup resets.
let resetAuthHeader: { Authorization: string } | undefined;

test.beforeAll(async ({ request }) => {
  const login = await request.post("/api/auth/login", {
    data: { username: "opuser", password: "op-pass-123" },
  });
  const { token } = (await login.json()) as { token: string };
  resetAuthHeader = { Authorization: `Bearer ${token}` };
});

test.beforeEach(async ({ request }) => {
  const mode = await request.post("/api/mode", {
    data: { mode: "sim" },
    headers: resetAuthHeader,
  });
  const reset = await request.post("/api/reset", { headers: resetAuthHeader });
  if (!mode.ok() || !reset.ok()) {
    throw new Error(`beforeEach reset failed: mode=${mode.status()} reset=${reset.status()}`);
  }
});

test("successful login shows the signed-in identity, logout clears it", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await login(page, OPERATOR);
  await expect(page.getByRole("button", { name: "Signed in as opuser" })).toBeVisible();
  // The popover stays open after a successful login (no auto-close), already showing the role.
  const account = page.getByRole("dialog", { name: "Account" });
  await expect(account.getByText("operator", { exact: true })).toBeVisible();
  await account.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Log in", exact: true }).first()).toBeVisible();

  expect(errors).toEqual([]);
});

test("invalid credentials show an inline error and leave the session logged out", async ({
  page,
}) => {
  await page.goto("/");
  await openLogin(page);
  await page.getByRole("textbox", { name: "Username" }).fill(OPERATOR.username);
  await page.getByRole("textbox", { name: "Password" }).fill("not-the-real-password");
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();

  await expect(page.getByText("Invalid username or password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in", exact: true }).first()).toBeVisible();
});

test("a tampered/invalid session token is rejected by the backend, not just the UI", async ({
  request,
}) => {
  // Real time-based expiry (AT_AUTH_TOKEN_TTL_S, default 8h) is impractical to wait out in a
  // test; a tampered signature exercises the identical `decode_token` rejection path an expired
  // token takes (`app/api/auth.py::decode_token` returns None for both malformed-and-expired
  // alike -- see `backend/tests/test_auth.py::test_token_expires` for the time-based case).
  const login = await request.post("/api/auth/login", { data: OPERATOR });
  const { token } = (await login.json()) as { token: string };
  const tampered = `${token}x`;

  const r = await request.post("/api/isolate", {
    data: { incident_id: "inc_001", node_id: "P101" },
    headers: { Authorization: `Bearer ${tampered}` },
  });
  expect(r.status()).toBe(401);
});

test("isolate is disabled with the exact reason when auth is required but missing", async ({
  page,
}) => {
  test.setTimeout(60_000); // the 40s expect below needs headroom past the 30s test default
  // Phase 5.3: launching an attack also requires login once AT_AUTH_SECRET is configured (the
  // demo API key alone is public, compiled into the browser bundle -- see
  // `require_operator_when_configured`), so this logs in to create the incident, then logs back
  // out to test the actual "missing" case: a session that ended (logout, or an expired token),
  // not "never logged in at all" -- the more realistic path to this state in practice.
  const errors = watchErrors(page);
  await page.goto("/");
  await login(page, OPERATOR);
  await page.getByRole("button", { name: "Launch" }).click();

  const incident = page.getByRole("region", { name: "Incident" });
  await expect(incident.getByTestId("incident-status")).toHaveText(/^(Incident|Ambiguous)$/, {
    timeout: 40_000,
  });

  await page.getByRole("button", { name: "Signed in as opuser" }).click();
  await page.getByRole("button", { name: "Log out" }).click();

  const isolate = incident.getByRole("button", { name: /^Isolate /, exact: false });
  await expect(isolate).toBeDisabled();
  await expect(isolate).toHaveAttribute("title", "Log in to isolate (top bar)");

  // Logging out while an incident is still open can trigger one trailing, now-unauthenticated
  // background request that the server correctly rejects with 401 -- that is the expected
  // consequence of this test's own scenario (ending the session mid-incident), not an app defect.
  expect(errors.filter((e) => !e.includes("401"))).toEqual([]);
});

test("unauthorized isolation (no token at all) is rejected by the backend", async ({
  request,
}) => {
  const r = await request.post("/api/isolate", {
    data: { incident_id: "inc_001", node_id: "P101" },
  });
  expect(r.status()).toBe(401);
});

test("the analyst role can log in but cannot isolate, and the UI reports why", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const errors = watchErrors(page);
  await page.goto("/");
  await login(page, ANALYST);
  await expect(page.getByRole("button", { name: "Signed in as anuser" })).toBeVisible();

  await page.getByRole("button", { name: "Launch" }).click();
  const incident = page.getByRole("region", { name: "Incident" });
  await expect(incident.getByTestId("incident-status")).toHaveText(/^(Incident|Ambiguous)$/, {
    timeout: 40_000,
  });

  // The frontend gates on "a token exists", not role (the backend is the real enforcement point,
  // Phase 1's design) -- so the button is enabled, and only the server's 403 stops it.
  const isolate = incident.getByRole("button", { name: /^Isolate /, exact: false });
  await expect(isolate).toBeEnabled();
  await isolate.click();
  // A refused attempt has no "isolate-state" element (that testid is only for pending/contained,
  // see IsolateButton.tsx) -- the refusal note renders as plain text under the button instead.
  await expect(incident.getByText("Your role cannot isolate")).toBeVisible({ timeout: 10_000 });

  expect(errors.filter((e) => !e.includes("403"))).toEqual([]);
});

test("the operator role completes a real authorized isolation (simulated plant, no real PLC)", async ({
  page,
}) => {
  // Localization is probabilistic (documented Top-1 accuracy ~0.84-0.88, see CLAUDE.md): the
  // top-ranked candidate is sometimes not the true origin, in which case isolating it correctly
  // never reaches "Contained" (app/engine.py Engine.isolate) and the UI offers the next-ranked
  // candidate instead (IsolateButton's designed retry affordance). This test exercises that real
  // workflow -- retry through candidates -- rather than assuming the first guess is always right.
  //
  // The attack is launched directly via the API (not the console's "Launch" button, which sends no
  // duration_s and gets the schema default of 60 plant-seconds) with a long duration: this run's
  // machine is heavily loaded (multiple docker stacks + browsers + this very suite), and detection
  // alone has taken over 30s elsewhere in this file -- a 60s attack can lapse before isolate is even
  // clicked, which (app/engine.py Engine.isolate: `effective` requires the attack still live) means
  // containment can never be reached no matter which node is isolated. A long duration removes that
  // race without weakening what's actually being tested (real login, real isolate, real containment).
  test.setTimeout(150_000); // up to a few isolate attempts, each waited out to its own ~30s verdict
  const errors = watchErrors(page);
  await page.goto("/");
  await login(page, OPERATOR);
  const launch = await page.request.post("/api/attack", {
    data: { scenario: "sensor_offset", target: "LIT101", magnitude: -25, duration_s: 600 },
    headers: resetAuthHeader,
  });
  if (!launch.ok()) throw new Error(`attack launch failed: ${launch.status()}`);

  const incident = page.getByRole("region", { name: "Incident" });
  await expect(incident.getByTestId("incident-status")).toHaveText(/^(Incident|Ambiguous)$/, {
    timeout: 40_000,
  });

  const isolateState = incident.getByTestId("isolate-state");
  let contained = false;
  for (let attempt = 0; attempt < 4 && !contained; attempt++) {
    const isolate = incident.getByRole("button", { name: /^Isolate /, exact: false });
    await expect(isolate).toBeEnabled();
    await isolate.click();
    try {
      await expect(isolateState).toHaveText(/Contained|Not contained/, { timeout: 35_000 });
    } catch {
      break; // stuck pending past the UI's own 30s not-contained timeout: a real failure, stop retrying
    }
    contained = (await isolateState.textContent())?.includes("Contained") ?? false;
  }
  expect(contained).toBe(true);
  // The verified token identity attributes the action, never a client-supplied field.
  await expect(incident.getByTestId("isolate-state")).toContainText("by opuser");
  await expect(page.getByRole("status", { name: "Status Normal" })).toBeVisible({
    timeout: 20_000,
  });

  expect(errors).toEqual([]);
});
