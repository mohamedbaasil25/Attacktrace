import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModeToggle } from "./ModeToggle";

const html = (props: Partial<Parameters<typeof ModeToggle>[0]> = {}): string =>
  renderToStaticMarkup(
    createElement(ModeToggle, {
      mode: "sim",
      haiAvailable: true,
      liveAvailable: false,
      onChange: () => undefined,
      ...props,
    }),
  );

/** The button tag for one mode, to check its real `disabled`/`title` attributes without matching
 *  the always-present `disabled:opacity-40` Tailwind variant class. */
function buttonFor(html: string, label: string): string {
  const after = html.split(`>${label}<`)[0] ?? "";
  const start = after.lastIndexOf("<button");
  return after.slice(start);
}

describe("ModeToggle: LIVE option", () => {
  it("shows all three modes", () => {
    const m = html();
    expect(m).toContain(">sim<");
    expect(m).toContain(">hai<");
    expect(m).toContain(">live<");
  });

  it("disables LIVE with the server's reason as the tooltip when unavailable", () => {
    const b = buttonFor(html({ liveAvailable: false, liveReason: "waiting for the plant source" }), "live");
    expect(b).toContain(' disabled=""');
    expect(b).toContain('title="waiting for the plant source"');
  });

  it("enables LIVE once the source is available", () => {
    const b = buttonFor(html({ liveAvailable: true }), "live");
    expect(b).not.toContain(" disabled=");
  });

  it("marks the active mode pressed", () => {
    const b = buttonFor(html({ mode: "live", liveAvailable: true }), "live");
    expect(b).toContain('aria-pressed="true"');
  });

  it("gives SIM no tooltip: it is always available", () => {
    const b = buttonFor(html(), "sim");
    expect(b).not.toContain(" disabled=");
    expect(b).not.toContain("title=");
  });
});
