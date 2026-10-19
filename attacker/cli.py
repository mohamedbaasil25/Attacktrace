"""`python -m attacker <scenario> <target> [--magnitude] [--duration] [--host] [--port]`

Launches one scenario against the plant emulator and waits for it to clear."""

import argparse
import asyncio
import logging

from app.attacks.engine import Scenario
from app.config import get_settings
from attacker.client import load_attacker

log = logging.getLogger("attacktrace.attacker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch one attack against the plant emulator")
    p.add_argument("scenario", choices=[s.value for s in Scenario])
    p.add_argument("target")
    p.add_argument("--magnitude", type=float, default=0.0)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--tagmap", default=None)
    return p.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    s = get_settings()
    atk = load_attacker(
        args.tagmap or str(s.live_tagmap),
        args.host or s.live_host,
        args.port or s.live_port,
        s.attacker_allowlist,
    )
    if not await atk.connect():
        log.error("could not connect to %s:%d", atk.host, atk.port)
        return 1
    attack_id = await atk.launch(
        Scenario(args.scenario), args.target, args.magnitude, args.duration
    )
    log.info("launched %s; waiting %.0f s for it to clear", attack_id, args.duration)
    await asyncio.sleep(args.duration + 0.5)
    await atk.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
