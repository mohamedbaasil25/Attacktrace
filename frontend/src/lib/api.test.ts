import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { postAttack, postReset, setMode } from "./api";

/** Phase 5.3: the demo API key (`VITE_API_KEY`) is compiled into the public browser bundle and
 *  is not authentication (see `app/api/security.py`'s `require_operator_when_configured`). Once
 *  a deployment configures real auth, the server requires a verified operator token on
 *  /api/attack, /api/reset and /api/mode too, not just /api/isolate -- these tests confirm the
 *  frontend actually sends one when it has one, so a logged-in operator's requests still work. */
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function authHeader(): string | null {
  const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
  const headers = init.headers as Record<string, string>;
  return headers.authorization ?? null;
}

describe("write calls attach the operator token when one is passed", () => {
  it("setMode", async () => {
    await setMode("sim", "tok123");
    expect(authHeader()).toBe("Bearer tok123");
  });

  it("postAttack", async () => {
    await postAttack({ scenario: "sensor_offset", target: "LIT101", magnitude: -25 }, "tok123");
    expect(authHeader()).toBe("Bearer tok123");
  });

  it("postReset", async () => {
    await postReset("tok123");
    expect(authHeader()).toBe("Bearer tok123");
  });

  it("omits the header entirely when no token is passed (unchanged pre-Phase-5.3 shape)", async () => {
    await postReset();
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect("authorization" in headers).toBe(false);
  });
});
