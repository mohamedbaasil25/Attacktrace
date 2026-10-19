import { expect, test, type Page } from "@playwright/test";

// Phase 14 C2: the "no console errors" leg of scripts/preflight.py. Loads the page as it stands
// right now (whatever mode/state the stack is already in) and asserts nothing logged an error --
// deliberately does not reset or change mode, so it never disturbs state another preflight check
// (or a presenter mid-rehearsal) is relying on.

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("preflight: the page loads with no console errors", async ({ page }) => {
  test.setTimeout(20_000);
  const errors = watchErrors(page);
  await page.goto("/");
  await expect(page.getByRole("status", { name: /^Status/ })).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(2_000); // let the first WS messages and any late errors land
  expect(errors).toEqual([]);
});
