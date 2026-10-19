"""Phase 14 C2: <=30s pre-demo checks, run after the stack is up (scripts/demo.py or `make demo`).

Checks: backend health, WS message rate (~2 Hz), frontend loads, API key configuration, current
mode, no browser console errors (via Playwright, reusing the existing frontend/e2e/ setup -- no
new dependency), and the emulator's reachability when LIVE mode is in play. Exits 0 only if every
check passes; prints one PASS/FAIL/SKIP line per check either way.
"""

import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://localhost:8000"
FRONTEND = "http://localhost:5173"
NPX = shutil.which("npx") or "npx"  # Windows: CreateProcess needs the resolved npx.cmd, not "npx"


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail else ""))
    return ok


def check_backend_health() -> tuple[bool, dict[str, object] | None]:
    try:
        with urllib.request.urlopen(f"{BACKEND}/api/status", timeout=5) as r:
            data = json.loads(r.read())
            return check("backend health", r.status == 200, f"mode={data['mode']}"), data
    except OSError as e:
        return check("backend health", False, str(e)), None


def check_frontend_loads() -> bool:
    try:
        with urllib.request.urlopen(FRONTEND, timeout=5) as r:
            return check("frontend loads", r.status == 200)
    except OSError as e:
        return check("frontend loads", False, str(e))


def check_key_configured() -> bool:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return check("API key configured", False, "no .env -- writes are open (local dev only)")
    key = None
    for line in env_path.read_text().splitlines():
        if line.startswith("AT_API_KEY="):
            key = line.split("=", 1)[1].strip()
    if not key:
        return check("API key configured", False, "AT_API_KEY is empty -- writes are open")
    if key == "change-me-demo-key":
        return check("API key configured", False, "AT_API_KEY is still the shipped placeholder")
    return check("API key configured", True)


async def check_ws_rate() -> bool:
    import websockets

    try:
        async with websockets.connect("ws://localhost:8000/ws/live", open_timeout=5) as ws:
            t0 = time.monotonic()
            n = 0
            while time.monotonic() - t0 < 3.0:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=1.0)
                    n += 1
                except TimeoutError:
                    pass
            rate = n / (time.monotonic() - t0)
            return check("WS message rate", 1.0 <= rate <= 3.0, f"{rate:.1f} msg/s (target ~2)")
    except OSError as e:
        return check("WS message rate", False, str(e))


def check_console_errors() -> bool:
    result = subprocess.run(
        [NPX, "playwright", "test", "e2e/preflight.spec.ts"],
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
        timeout=30,
    )
    ok = result.returncode == 0
    return check("no browser console errors", ok, "" if ok else result.stdout[-300:])


def check_emulator(status: dict[str, object] | None) -> bool:
    if status is None:
        return check("emulator reachable", False, "backend health check failed first")
    if status.get("mode") != "live" and not status.get("live_available"):
        print("SKIP  emulator reachable -- not in LIVE mode and LIVE isn't available")
        return True
    try:
        with urllib.request.urlopen("http://localhost:8081/health", timeout=3) as r:
            return check("emulator reachable", r.status == 200)
    except OSError as e:
        return check("emulator reachable", False, str(e))


def main() -> int:
    t0 = time.monotonic()
    ok1, status = check_backend_health()
    results = [
        ok1,
        check_frontend_loads(),
        check_key_configured(),
        asyncio.run(check_ws_rate()),
        check_console_errors(),
        check_emulator(status),
    ]
    elapsed = time.monotonic() - t0
    print(f"\n{sum(results)}/{len(results)} checks passed in {elapsed:.1f}s")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
