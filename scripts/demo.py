"""Phase 14 C2: start the stack, wait for it to be healthy, reset, wait the measured warm-up,
print READY and the click path to run live. The click path is read from reports/demo_trials.json
(the Phase 14 C1 measured primary) when it exists, so it reflects real numbers, not a guess; falls
back to the documented default (sensor_offset/LIT101) otherwise.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"
SETTLE_S = 30.0  # matches eval/demo_trials.py's SIM_SETTLE_S: the detector's steady-state warm-up


def wait_healthy(timeout_s: float = 300.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"{BASE}/api/status", timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def post(path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    key = os.environ.get("AT_API_KEY", "")
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json", **({"x-api-key": key} if key else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())  # type: ignore[no-any-return]


def click_path() -> tuple[str, str, str]:
    trials = ROOT / "reports" / "demo_trials.json"
    if trials.exists():
        data = json.loads(trials.read_text())
        sim = data.get("sim")
        if sim:
            p = sim["primary"]
            sc, tg = p["pair"].split("/")
            return sc, tg, f"measured: Top-1 {p['top1_rate']:.0%} over {p['n']} fresh trials"
    return "sensor_offset", "LIT101", "default -- run eval.demo_trials for a measured pick"


def main() -> int:
    print("starting the stack (docker compose up -d --build)...")
    try:
        subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"docker compose failed: {e}", file=sys.stderr)
        return 1

    print("waiting for the backend to report healthy...")
    if not wait_healthy():
        print("backend never became healthy within 5 minutes", file=sys.stderr)
        return 1

    print("resetting...")
    try:
        post("/api/reset")
    except urllib.error.HTTPError as e:
        print(f"reset failed: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
        return 1

    print(f"warming up ({SETTLE_S:.0f}s, matches the measured settle time)...")
    time.sleep(SETTLE_S)

    sc, tg, note = click_path()
    print()
    print("READY")
    print("  1. Open http://localhost:5173")
    print(f"  2. Attack console: scenario {sc}, target {tg}, Launch  ({note})")
    print("  3. Watch the pill turn Incident, then the panel name the origin")
    print(f"  4. Isolate {tg} -> Contained")
    print("  5. Metrics page for the headline numbers")
    print()
    print("Run scripts/preflight.py now to confirm everything is actually working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
