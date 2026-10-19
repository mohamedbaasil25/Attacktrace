"""`python -m plant_emulator`: run the emulator until interrupted. Settings come from the
environment (EMU_HOST, EMU_PORT, EMU_HEALTH_PORT, EMU_SEED, EMU_HZ, EMU_TAGMAP)."""

import asyncio
import contextlib
import logging
import os
import signal
import sys

from app.live.tagmap import TagMapError, load_tagmap
from plant_emulator.server import PlantEmulator

log = logging.getLogger("plant_emulator")


async def main() -> int:
    try:
        tagmap = load_tagmap(os.environ.get("EMU_TAGMAP", "config/tagmap.yaml"))
    except TagMapError as exc:
        log.error("%s", exc)
        return 2
    emu = PlantEmulator(
        tagmap,
        seed=int(os.environ.get("EMU_SEED", "42")),
        host=os.environ.get("EMU_HOST", "127.0.0.1"),
        port=int(os.environ.get("EMU_PORT", "5020")),
        health_port=int(os.environ.get("EMU_HEALTH_PORT", "8081")),
        hz=float(os.environ.get("EMU_HZ", "10")),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: Ctrl+C raises instead
            loop.add_signal_handler(sig, stop.set)
    await emu.start()
    log.info(
        "emulator up: modbus %s:%d, health :%s, seed %d",
        emu.host,
        emu.port,
        emu.health_port,
        emu.seed,
    )
    try:
        await stop.wait()
    finally:
        await emu.stop()
        log.info("emulator stopped")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main()))
