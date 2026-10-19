"""Demo rehearsal: launch each scenario three times against the live API and log what happens.

Needs the backend on :8000 (SIM mode). Runs in real time (the plant steps at 2 Hz), so 15 runs take
several minutes. For each run it records:
  detected        an incident appeared before the timeout
  detect_s        seconds from launch to the first incident message
  localized_s     seconds from launch to the incident reaching status "open" (window complete);
                  this is the "time-to-localize" used by `make eval` (alert + 10 s window)
  origin_top3     origin candidates at that moment (the API exposes the top 3 only)
  rank            1-3 if the true target is in the top 3, else ">3"

    python submission/tools/rehearsal.py [--timeout 90] [--duration 60] [--settle 30] [--tag _x] [--out dir]

--settle is the quiet time after `reset` before the attack. The default (30 s, the detector is in
steady state) matches a demo; `--settle 4 --tag _cold_start` reproduces the cold-start log.
"""

import argparse
import asyncio
import json
import time
import os
import urllib.request
from pathlib import Path

import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws/live"

# (scenario, target, magnitude): three runs per scenario, on different targets where the
# scenario allows it (rogue_setpoint has only two targets, so the third run flips the sign).
RUNS: list[tuple[str, str, float]] = [
    ("sensor_freeze", "LIT101", 0.0),
    ("sensor_freeze", "LIT301", 0.0),
    ("sensor_freeze", "FIT201", 0.0),
    ("sensor_offset", "LIT101", -25.0),
    ("sensor_offset", "LIT301", 25.0),
    ("sensor_offset", "PIT301", 0.6),
    ("sensor_ramp", "LIT101", 30.0),
    ("sensor_ramp", "LIT301", 30.0),
    ("sensor_ramp", "FIT201", 3.6),
    ("actuator_force", "MV101", 1.0),
    ("actuator_force", "P101", 0.0),
    ("actuator_force", "P301", 0.0),
    ("rogue_setpoint", "PLC1", 25.0),
    ("rogue_setpoint", "PLC2", -25.0),
    ("rogue_setpoint", "PLC1", -25.0),
]


KEY = os.environ.get("AT_API_KEY", "")


def post(path: str, body: dict | None = None) -> dict:  # sends AT_API_KEY when set
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json", **({"x-api-key": KEY} if KEY else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


async def one_run(
    scenario: str, target: str, magnitude: float, timeout: float, settle: float, duration: float
) -> dict:
    post("/api/mode", {"mode": "sim"})
    post("/api/reset")
    async with websockets.connect(WS) as ws:
        quiet = time.monotonic()
        while time.monotonic() - quiet < settle:  # quiet plant: the detector reaches steady state
            msg = json.loads(await ws.recv())
            assert msg["incident"] is None, "reset left an incident behind"
        body = {"scenario": scenario, "target": target, "magnitude": magnitude, "duration_s": duration}
        attack_id = post("/api/attack", body)["attack_id"]
        t0 = time.monotonic()
        first: float | None = None
        opened: float | None = None
        last: dict | None = None
        while time.monotonic() - t0 < timeout:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except TimeoutError:
                continue
            inc = msg["incident"]
            if not inc:
                continue
            now = time.monotonic() - t0
            first = first if first is not None else now
            last = inc
            if inc["status"] == "open":
                opened = now
                break
    row: dict = {
        "scenario": scenario,
        "target": target,
        "magnitude": magnitude,
        "attack_id": attack_id,
        "detected": last is not None,
        "detect_s": None if first is None else round(first, 1),
        "localized_s": None if opened is None else round(opened, 1),
        "origin_top3": [o["id"] for o in last["origin"]] if last else [],
        "origin_conf": [round(o["confidence"], 2) for o in last["origin"]] if last else [],
        "mitre": last["mitre"] if last else None,
    }
    ids = row["origin_top3"]
    row["rank"] = ids.index(target) + 1 if target in ids else (">3" if last else None)
    return row


async def main(timeout: float, out: Path, settle: float, tag: str, duration: float) -> None:
    rows = []
    for i, (sc, tg, mag) in enumerate(RUNS, 1):
        row = await one_run(sc, tg, mag, timeout, settle, duration)
        rows.append(row)
        print(
            f"[{i:2d}/{len(RUNS)}] {sc:15s} {tg:7s} detected={'Y' if row['detected'] else 'N'} "
            f"rank={row['rank']} detect={row['detect_s']}s localized={row['localized_s']}s "
            f"top3={row['origin_top3']}",
            flush=True,
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / f"rehearsal{tag}.json").write_text(json.dumps(rows, indent=1))
    lines = [
        "| Scenario | Target | Detected | Rank of true origin | Detect (s) | Localized (s) | Top-3 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['target']} | {'Y' if r['detected'] else 'N'} | "
            f"{r['rank'] if r['rank'] is not None else 'n/a'} | "
            f"{r['detect_s'] if r['detect_s'] is not None else 'n/a'} | "
            f"{r['localized_s'] if r['localized_s'] is not None else 'n/a'} | "
            f"{', '.join(r['origin_top3']) or 'n/a'} |"
        )
    (out / f"rehearsal{tag}.md").write_text("\n".join(lines) + "\n")
    hit = [r for r in rows if r["detected"]]
    top1 = sum(1 for r in rows if r["rank"] == 1)
    print(f"\ndetected {len(hit)}/{len(rows)}; true origin ranked 1st in {top1}/{len(rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--duration", type=float, default=60.0, help="attack length; the UI always sends 60")
    ap.add_argument("--out", type=Path, default=Path("submission/evidence"))
    ap.add_argument("--settle", type=float, default=30.0, help="quiet seconds after reset, before launch")
    ap.add_argument("--tag", default="", help="suffix for the output files, e.g. _cold_start")
    a = ap.parse_args()
    asyncio.run(main(a.timeout, a.out, a.settle, a.tag, a.duration))
