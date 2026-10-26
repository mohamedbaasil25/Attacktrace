"""Phase 16 B2: LIVE end-to-end latency -- client-issued attack launch -> WebSocket message that
reflects it, measured against the ALREADY-RUNNING main docker stack (backend :8000, plant-emulator
already up), not a fresh ad-hoc harness. This is intentionally a DIFFERENT, larger latency than
`live_metrics.json`'s existing figure (the Modbus READ round-trip measured inside the backend
process -- see `fix_analysis.json.latency_and_timing.live_latency_ms`), not end-to-end delivery to
a connected client.

Measured here: wall-clock from issuing `POST /api/attack` (the client's own send time) to the first
`/ws/live` message whose `incident` field reflects a NEW incident. This is a client-to-client,
over-the-wire latency (HTTP request + server-side processing + WS broadcast + network), a strictly
larger and more realistic number than the pure read latency.

Labeled a separate measurement per Phase 16 rule 1/3 (fresh, not folded into live_metrics.json).
Switches the running backend to LIVE mode for the run and back to SIM afterward -- a mode switch,
not a config/model change. Uses `demo`/`demo`, the project's own published demo operator account
(not a secret -- see README), to authenticate the mode-switch/attack calls now required once
AT_AUTH_SECRET is configured (Phase 5.3's `require_operator_when_configured`). The demo API key is
read directly from the repo-root `.env` at runtime and never printed or logged anywhere.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

BASE_HTTP = "http://localhost:8000"
BASE_WS = "ws://localhost:8000/ws/live"


def _read_api_key() -> str:
    """Reads AT_API_KEY straight from the repo-root .env -- never printed, never logged."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("AT_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("AT_API_KEY not found in .env")


N_CLEAN_MINUTES = 10.0
ATTACKS = [
    # Fresh labeling only (LIVE attacks are parameterized directly, not RNG-seeded like SIM's
    # sample_attack); run id "6000-series" per Phase 16 rule 3's fresh-seed-bucket convention.
    {"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25.0, "duration_s": 60.0},
    {"scenario": "sensor_freeze", "target": "LIT301", "magnitude": 0.0, "duration_s": 60.0},
    {"scenario": "actuator_force", "target": "MV101", "magnitude": 1.0, "duration_s": 60.0},
    {"scenario": "rogue_setpoint", "target": "PLC1", "magnitude": 20.0, "duration_s": 60.0},
    {"scenario": "sensor_ramp", "target": "FIT201", "magnitude": 3.0, "duration_s": 60.0},
]


@dataclass
class Samples:
    ws_connect_ok: bool = False
    clean_messages: int = 0
    clean_window_s: float = 0.0
    attack_latencies_s: list[float] = field(default_factory=list)
    attack_results: list[dict[str, object]] = field(default_factory=list)
    dropped_or_timeout: int = 0
    quiet_wait_timeouts: int = 0


def _login(client: httpx.Client) -> str:
    r = client.post(f"{BASE_HTTP}/api/auth/login", json={"username": "demo", "password": "demo"})
    r.raise_for_status()
    token: str = r.json()["token"]
    return token


def _set_mode(client: httpx.Client, token: str, mode: str) -> None:
    r = client.post(
        f"{BASE_HTTP}/api/mode",
        json={"mode": mode},
        headers={"Authorization": f"Bearer {token}", "X-API-Key": _read_api_key()},
    )
    r.raise_for_status()


async def _wait_until_quiet(client: httpx.Client, token: str, max_wait_s: float = 90.0) -> bool:
    """Phase 16 B2 re-run fix: the first run fired 5 attacks only 5s apart, so later attacks'
    activity often folded into an incident the previous attack had already opened (same baseline
    incident id -> this script's "new incident" detector never fired -> 4 of 5 attacks read as
    "no incident observed" even though incidents genuinely did form, confirmed via direct API
    inspection at the time). Waiting for the PREVIOUS incident to fully close before firing the
    next attack makes each attack's baseline genuinely "no incident", matching how an operator
    would actually use the system (one incident at a time) rather than stress-testing concurrent
    incident admission (a separate, already-documented limitation -- see UI_SPEC.md 7.1).
    Returns False (and gives up) if still not quiet after max_wait_s."""
    deadline = time.monotonic() + max_wait_s
    headers = {"Authorization": f"Bearer {token}", "X-API-Key": _read_api_key()}
    while time.monotonic() < deadline:
        r = client.get(f"{BASE_HTTP}/api/incidents", headers=headers)
        r.raise_for_status()
        incidents = r.json()
        if not incidents or incidents[0].get("status") == "closed":
            return True
        await asyncio.sleep(3)
    return False


async def _listen_clean(samples: Samples, seconds: float, ws_url: str) -> None:
    deadline = time.monotonic() + seconds
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        samples.ws_connect_ok = True
        start = time.monotonic()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(ws.recv(), timeout=remaining)
                samples.clean_messages += 1
            except TimeoutError:
                break
        samples.clean_window_s = time.monotonic() - start


async def _attack_and_measure(
    client: httpx.Client, token: str, samples: Samples, spec: dict[str, object], ws_url: str
) -> None:
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        # Drain one message to get a baseline incident id/state before launching.
        try:
            baseline_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            baseline = json.loads(baseline_raw)
        except TimeoutError:
            baseline = {}
        baseline_inc_id = (baseline.get("incident") or {}).get("id")

        send_t = time.monotonic()
        r = client.post(
            f"{BASE_HTTP}/api/attack",
            json=spec,
            headers={"Authorization": f"Bearer {token}", "X-API-Key": _read_api_key()},
        )
        r.raise_for_status()

        latency_s: float | None = None
        for _ in range(90):  # up to ~90 WS messages / ~45s at 2Hz before giving up
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except TimeoutError:
                break
            msg = json.loads(raw)
            inc = msg.get("incident")
            if inc is not None and inc.get("id") != baseline_inc_id:
                latency_s = time.monotonic() - send_t
                break
        if latency_s is not None:
            samples.attack_latencies_s.append(latency_s)
            samples.attack_results.append({"scenario": spec["scenario"], "latency_s": latency_s})
        else:
            samples.dropped_or_timeout += 1
            samples.attack_results.append(
                {"scenario": spec["scenario"], "latency_s": None, "note": "no incident observed"}
            )


async def _run(samples: Samples) -> None:
    with httpx.Client(timeout=10) as client:
        token = _login(client)
        # Browsers can't set a custom Authorization header on a WS handshake, so the backend
        # accepts the token as a query param instead (app/api/ws.py:_ws_operator_ok) -- this
        # script is a non-browser client, but AT_AUTH_SECRET is configured on the running stack,
        # so it needs the same token too, or the handshake is rejected (4401, surfaced as a flat
        # HTTP 403 by uvicorn for any pre-accept close).
        ws_url = f"{BASE_WS}?token={token}"
        _set_mode(client, token, "live")
        try:
            await _listen_clean(samples, N_CLEAN_MINUTES * 60, ws_url)
            for spec in ATTACKS:
                quiet = await _wait_until_quiet(client, token)
                if not quiet:
                    samples.quiet_wait_timeouts += 1
                await asyncio.sleep(2)  # brief settle after the quiet check itself
                await _attack_and_measure(client, token, samples, spec, ws_url)
        finally:
            _set_mode(client, token, "sim")  # restore the demo stack's resting state


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def analyze() -> dict[str, object]:
    samples = Samples()
    asyncio.run(_run(samples))
    lat = samples.attack_latencies_s
    return {
        "definition": "wall-clock from this client's POST /api/attack send time to the first "
        "/ws/live message whose incident id differs from the pre-attack baseline -- includes HTTP "
        "request, server processing/detection-to-incident-open, and WS broadcast; NOT the same as "
        "live_metrics.json's existing figure (Modbus read round-trip only).",
        "target_p95_s": 1.0,
        "ws_connect_ok": samples.ws_connect_ok,
        "clean_window_s": samples.clean_window_s,
        "clean_messages_received": samples.clean_messages,
        "clean_messages_per_s": samples.clean_messages / samples.clean_window_s
        if samples.clean_window_s
        else None,
        "quiet_wait_timeouts": samples.quiet_wait_timeouts,
        "n_attacks": len(ATTACKS),
        "n_with_latency": len(lat),
        "n_dropped_or_timeout": samples.dropped_or_timeout,
        "attack_results": samples.attack_results,
        "p50_s": _percentile(lat, 0.5),
        "p95_s": _percentile(lat, 0.95),
        "p99_s": _percentile(lat, 0.99),
        "p95_meets_target": (_percentile(lat, 0.95) or float("inf")) < 1.0 if lat else None,
    }


def main() -> int:
    from eval.analysis._util import merge_write_final

    result = analyze()
    from pathlib import Path

    out = merge_write_final("b2_live_e2e_latency", result)
    Path("..", "submission", "evidence", "b2_live_e2e_latency.json").write_text(
        json.dumps(result, indent=1)
    )
    print(
        f"wrote {out}: p50={result['p50_s']} p95={result['p95_s']} p99={result['p99_s']} "
        f"n_with_latency={result['n_with_latency']}/{result['n_attacks']} "
        f"dropped={result['n_dropped_or_timeout']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
