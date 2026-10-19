"""Phase 13 Part F: 60-minute LIVE soak test with periodic attacks and two forced reconnects.

`python -m eval.live_soak` (`make live-soak`) spawns its own plant-emulator subprocess (so it can
kill and restart it), runs the trained LIVE engine against it for `--minutes` (default 60),
launches one attack every `--attack-every` minutes, and force-kills the emulator twice at roughly
1/3 and 2/3 through the run to prove the source reconnects on its own. It records a memory/CPU
sample every 30 s and writes `reports/live_soak.json`. No new dependency: memory comes from
`resource` on POSIX or a small `ctypes` call on Windows; CPU from `time.process_time()`.
"""

import argparse
import asyncio
import contextlib
import ctypes
import json
import logging
import os
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

try:
    import attacker  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from attacker.client import AttackerClient

from app.attacks.engine import Scenario
from app.config import Settings, get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.graph import load_graph
from app.live.config import load_live
from app.live.engine import LiveEngine
from app.live.source import LiveSource
from app.live.train import live_dir, live_models_ready

log = logging.getLogger("attacktrace.eval.live_soak")

SAMPLE_PERIOD_S = 30.0
DEFAULT_MINUTES = 60.0
ATTACK_EVERY_MIN = 10.0
ATTACK_DURATION_S = 60.0
TICK_S = 0.5
EMU_HEALTH_TIMEOUT_S = 20.0


def _rss_mb() -> float | None:
    """Resident memory of this process, in MB; None if it cannot be read."""
    if platform.system() == "Windows":
        try:
            # Without explicit restype/argtypes, ctypes truncates the 64-bit HANDLE values
            # through the default `int` return type and every call below silently fails.
            get_current_process = ctypes.windll.kernel32.GetCurrentProcess
            get_current_process.restype = ctypes.c_void_p
            handle = get_current_process()

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_uint32),
                    ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(ProcessMemoryCounters)
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            get_process_memory_info.restype = ctypes.c_int
            ok = get_process_memory_info(handle, ctypes.byref(counters), counters.cb)
            return counters.WorkingSetSize / 1e6 if ok else None
        except OSError:
            return None
    try:
        import resource  # POSIX only; this branch never runs on Windows

        # typeshed only declares getrusage/RUSAGE_SELF for POSIX platforms.
        kb: int = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # type: ignore[attr-defined]
        return kb / 1024.0  # ru_maxrss is in KB on Linux
    except ImportError:
        return None


@dataclass
class Sample:
    t: float
    rss_mb: float | None
    cpu_pct: float | None
    source_state: str
    engine_ok: bool


@dataclass
class ReconnectEvent:
    killed_at: float
    recovered_at: float | None  # None if it never came back within the timeout


@dataclass
class SoakState:
    samples: list[Sample] = field(default_factory=list)
    reconnects: list[ReconnectEvent] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    attacks_launched: int = 0


def spawn_emulator(port: int, health_port: int, seed: int) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env.update(EMU_PORT=str(port), EMU_HEALTH_PORT=str(health_port), EMU_SEED=str(seed))
    return subprocess.Popen(
        [sys.executable, "-m", "plant_emulator"],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def wait_healthy(health_port: int, timeout_s: float) -> bool:
    import urllib.error
    import urllib.request

    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            await asyncio.to_thread(
                urllib.request.urlopen, f"http://127.0.0.1:{health_port}/health", None, 2
            )
            return True
        except (urllib.error.URLError, OSError):
            await asyncio.sleep(0.5)
    return False


async def run(settings: Settings, minutes: float, attack_every_min: float) -> dict[str, object]:
    if not live_models_ready(settings.models_dir):
        raise SystemExit("no LIVE model: run `make live-train` first")
    cfg, tagmap = load_live(settings)
    emu = spawn_emulator(cfg.port, 18099, settings.seed)
    try:
        if not await wait_healthy(18099, EMU_HEALTH_TIMEOUT_S):
            raise SystemExit("spawned emulator never became healthy")

        d = live_dir(settings.models_dir)
        kind = str(json.loads((d / "detector.json").read_text())["active"])
        source = LiveSource(cfg, tagmap)
        engine = LiveEngine(
            load_detector(d), load_baseline(d), load_graph(d / "graph.json"), settings, source, kind
        )
        attacker_client = AttackerClient(cfg.host, cfg.port, tagmap, settings.attacker_allowlist)
        await source.start()
        await attacker_client.connect()
        for _ in range(100):
            if source.ready:
                break
            await asyncio.sleep(0.2)

        state = SoakState()
        t_start = time.perf_counter()
        t_cpu0, wall0 = time.process_time(), time.perf_counter()
        next_sample = t_start
        next_attack = t_start + attack_every_min * 60.0
        reconnect_marks = [t_start + minutes * 60.0 / 3.0, t_start + 2.0 * minutes * 60.0 / 3.0]
        pending_reconnect: ReconnectEvent | None = None
        end = t_start + minutes * 60.0

        def rotate_attack() -> tuple[Scenario, str, float]:
            scenarios = list(Scenario)
            sc = scenarios[state.attacks_launched % len(scenarios)]
            from app.attacks.engine import VALID_TARGETS

            target = VALID_TARGETS[sc][0]
            return sc, target, -10.0 if sc.value.startswith("sensor") else 0.5

        while time.perf_counter() < end:
            loop_t0 = time.perf_counter()
            try:
                engine.step_sample()
                engine_ok = True
            except Exception:
                engine_ok = False
                state.exceptions.append(traceback.format_exc())
                log.exception("step_sample failed during soak")

            now = time.perf_counter()
            if now >= next_sample:
                cpu_pct = 100.0 * (time.process_time() - t_cpu0) / max(1e-9, now - wall0)
                state.samples.append(
                    Sample(now - t_start, _rss_mb(), cpu_pct, source.status().state, engine_ok)
                )
                next_sample += SAMPLE_PERIOD_S

            if now >= next_attack and source.ready:
                sc, target, mag = rotate_attack()
                try:
                    await attacker_client.launch(sc, target, mag, ATTACK_DURATION_S)
                    state.attacks_launched += 1
                    log.info("soak attack %d: %s on %s", state.attacks_launched, sc.value, target)
                except Exception:
                    state.exceptions.append(traceback.format_exc())
                    log.exception("attack launch failed during soak")
                next_attack += attack_every_min * 60.0

            if reconnect_marks and now >= reconnect_marks[0]:
                reconnect_marks.pop(0)
                log.info("killing the emulator to test reconnect")
                emu.kill()
                emu.wait(timeout=10)
                pending_reconnect = ReconnectEvent(killed_at=now - t_start, recovered_at=None)
                await asyncio.sleep(2.0)  # give the poller a moment to notice the drop
                emu = spawn_emulator(cfg.port, 18099, settings.seed)
                if not await wait_healthy(18099, EMU_HEALTH_TIMEOUT_S):
                    log.error("restarted emulator never became healthy")

            if pending_reconnect is not None and source.status().connected:
                pending_reconnect.recovered_at = now - t_start
                state.reconnects.append(pending_reconnect)
                pending_reconnect = None

            await asyncio.sleep(max(0.0, TICK_S - (time.perf_counter() - loop_t0)))

        if pending_reconnect is not None:
            state.reconnects.append(pending_reconnect)  # never recovered: recorded as such
        await attacker_client.close()
        await source.stop()
        return _summarize(state, time.perf_counter() - t_start)
    finally:
        emu.kill()
        with contextlib.suppress(Exception):
            emu.wait(timeout=5)


def _summarize(state: SoakState, uptime_s: float) -> dict[str, object]:
    rss = [s.rss_mb for s in state.samples if s.rss_mb is not None]
    growth_mb = (rss[-1] - rss[0]) if len(rss) >= 2 else None
    return {
        "uptime_s": uptime_s,
        "n_samples": len(state.samples),
        "n_attacks": state.attacks_launched,
        "n_exceptions": len(state.exceptions),
        "exceptions": state.exceptions[:5],  # first few, not the whole traceback dump
        "memory_mb": {
            "first": rss[0] if rss else None,
            "last": rss[-1] if rss else None,
            "peak": max(rss) if rss else None,
            "growth": growth_mb,
        },
        "cpu_pct": {
            "mean": sum(s.cpu_pct for s in state.samples if s.cpu_pct is not None)
            / max(1, sum(1 for s in state.samples if s.cpu_pct is not None)),
        },
        "reconnects": [
            {
                "killed_at_s": r.killed_at,
                "recovered_at_s": r.recovered_at,
                "recovered": r.recovered_at is not None,
            }
            for r in state.reconnects
        ],
        "n_reconnects_attempted": len(state.reconnects),
        "n_reconnects_succeeded": sum(1 for r in state.reconnects if r.recovered_at is not None),
        "samples": [
            {
                "t": s.t,
                "rss_mb": s.rss_mb,
                "cpu_pct": s.cpu_pct,
                "source_state": s.source_state,
                "engine_ok": s.engine_ok,
            }
            for s in state.samples
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    ap.add_argument("--attack-every", type=float, default=ATTACK_EVERY_MIN)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = get_settings()
    result = asyncio.run(run(settings, args.minutes, args.attack_every))
    out = Path(args.out) if args.out else settings.reports_dir / "live_soak.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    log.info(
        "wrote %s: %d exceptions, %d/%d reconnects, memory %.0f -> %.0f MB",
        out,
        result["n_exceptions"],
        result["n_reconnects_succeeded"],
        result["n_reconnects_attempted"],
        (result["memory_mb"]["first"] or 0),  # type: ignore[index]
        (result["memory_mb"]["last"] or 0),  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
