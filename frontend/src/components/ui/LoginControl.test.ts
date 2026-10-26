import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LoginControl } from "./LoginControl";

const html = (): string => renderToStaticMarkup(createElement(LoginControl));

// zustand's SSR snapshot (`getInitialState`, see node_modules/zustand/react.js) is fixed at store
// creation and does not reflect a later `setState` under `renderToStaticMarkup`, so only the
// logged-out (initial) render is checkable here. The logged-in markup and the actual login/logout
// transitions are exercised by `store/auth.test.ts` (the store itself) and live browser
// verification; this test's job is just the regression it guards: a compact icon trigger, not the
// removed always-visible Username/Password form.
describe("LoginControl", () => {
  it("renders a compact icon-only trigger when logged out, not an always-visible form", () => {
    const m = html();
    expect(m).toContain('aria-label="Log in"');
    // the popover's username/password fields are not in the initial (closed) markup
    expect(m).not.toContain('aria-label="Username"');
    expect(m).not.toContain('aria-label="Password"');
  });
});
