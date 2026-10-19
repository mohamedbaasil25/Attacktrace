"""Phase 13 Part F: seeded evaluation of LIVE mode through the real protocol path.

`python -m eval.live` (`make eval-live`) needs the emulator running (`make emulator`) and a
trained LIVE detector (`make live-train`). It runs, in real time:
  1. a clean session (default 60 min) to measure the false-alarm rate, and
  2. a fixed, seeded set of attacks per scenario, launched through the attacker module exactly as
     an operator's UI click would, to measure detection, localization and latency.

Every number in `reports/live_metrics.json` comes from this run; nothing here is tuned against it
(the detector and its threshold were already fixed by `make live-train`), and the seeds
(LIVE_TEST_SEEDS) were never used for that training or for any SIM evaluation.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import attacker  # noqa: F401
except ModuleNotFoundError:
    # `python -m eval.live` run directly from backend/ without pytest's `pythonpath` config.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from attacker.allowlist import check_host
from attacker.client import AttackerClient

from app.attacks.engine import Scenario
from app.config import Settings, get_settings
from app.data.simdata import sample_attack
from app.detect.pipeline import load_baseline
from app.graph import load_graph
from app.live.config import load_live
from app.live.engine import LiveEngine
from app.live.source import LiveSource
from app.live.train import live_dir, live_models_ready
from app.schemas import Incident

log = logging.getLogger("attacktrace.eval.live")

LIVE_TEST_SEEDS = range(3000, 3006)  # 6 per scenario; disjoint from every SIM/HAI seed range
ATTACK_DURATION_S = 120.0  # matches SIM's seeded attacks for a fair comparison
GAP_S = 90.0  # quiet time after each attack: lets the incident close (needs 30 s) before the next
RECOVERY_S = 60.0  # post-attack seconds excluded from the false-alarm count, as in SIM
DEFAULT_CLEAN_MIN = 60.0
TICK_S = 0.5


@dataclass
class Sample:
    t: float
    alerting: bool
    label: int  # 1 = attack active, -1 = ignored (recovery), 0 = clean


@dataclass
class AttackResult:
    scenario: str
    target: str
    detected: bool
    top1: bool
    top3: bool
    time_to_localize_s: float | None  # launch -> incident `open`
    detection_delay_s: float | None  # launch -> first alert
    # Phase 14 C1 (additive): read off the opened incident for free, no behaviour change.
    ambiguous: bool | None = None


@dataclass
class LiveEvalState:
    engine: LiveEngine
    source: LiveSource
    attacker: AttackerClient
    samples: list[Sample] = field(default_factory=list)
    _last_incident_id: str | None = None

    async def tick(self, label: int) -> Incident | None:
        """One engine step; records the sample and returns a newly OPENED incident, if any."""
        t0 = time.perf_counter()
        msg = self.engine.step_sample()
        dt = time.perf_counter() - t0
        if dt > 1.0:
            log.warning("decision latency %.2fs exceeded 1s", dt)
        self.samples.append(Sample(time.time(), msg.alert is not None, label))
        inc = msg.incident
        if inc is not None and inc.status == "open" and inc.id != self._last_incident_id:
            self._last_incident_id = inc.id
            return inc
        return None

    async def run_quiet(self, seconds: float, label: int = 0) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            t0 = time.perf_counter()
            await self.tick(label)
            await asyncio.sleep(max(0.0, TICK_S - (time.perf_counter() - t0)))

    async def run_attack(self, scenario: Scenario, target: str, magnitude: float) -> AttackResult:
        launch_wall = time.time()
        await self.attacker.launch(scenario, target, magnitude, ATTACK_DURATION_S)
        opened: Incident | None = None
        first_alert: float | None = None
        end = time.perf_counter() + ATTACK_DURATION_S + 20.0  # a little slack past the attack end
        while time.perf_counter() < end:
            t0 = time.perf_counter()
            label = 1 if time.time() - launch_wall < ATTACK_DURATION_S else -1
            inc = await self.tick(label)
            if self.samples[-1].alerting and first_alert is None:
                first_alert = self.samples[-1].t
            if inc is not None and opened is None:
                opened = inc
            await asyncio.sleep(max(0.0, TICK_S - (time.perf_counter() - t0)))
        await self.run_quiet(max(0.0, GAP_S - 20.0), label=-1)  # the rest of the gap: recovery
        if opened is None:
            return AttackResult(scenario.value, target, False, False, False, None, None)
        ids = [c.id for c in opened.origin]
        return AttackResult(
            scenario=scenario.value,
            target=target,
            detected=True,
            top1=ids[0] == target if ids else False,
            top3=target in ids[:3],
            time_to_localize_s=opened.detected_at - launch_wall,
            detection_delay_s=(first_alert - launch_wall) if first_alert is not None else None,
            ambiguous=opened.ambiguous,
        )


def _rising_edges(alerting: list[bool]) -> int:
    return sum(1 for i in range(1, len(alerting)) if alerting[i] and not alerting[i - 1]) + (
        1 if alerting and alerting[0] else 0
    )


def _prf(samples: list[Sample]) -> dict[str, float]:
    tp = sum(1 for s in samples if s.label == 1 and s.alerting)
    fp = sum(1 for s in samples if s.label == 0 and s.alerting)
    fn = sum(1 for s in samples if s.label == 1 and not s.alerting)
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    return {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-12)}


def _false_alarm_per_hour(samples: list[Sample]) -> float:
    clean = [s for s in samples if s.label == 0]
    if len(clean) < 2:
        return 0.0
    hours = (clean[-1].t - clean[0].t) / 3600.0
    return _rising_edges([s.alerting for s in clean]) / hours if hours > 0 else 0.0


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def build_state(settings: Settings) -> LiveEvalState:
    if not live_models_ready(settings.models_dir):
        raise SystemExit("no LIVE model: run `make live-train` first")
    cfg, tagmap = load_live(settings)
    d = live_dir(settings.models_dir)
    from app.detect.pipeline import load_detector

    loaded = load_detector(d)
    kind = str(json.loads((d / "detector.json").read_text())["active"])
    graph = load_graph(d / "graph.json")
    source = LiveSource(cfg, tagmap)
    # The poller's latency deque is sized for a live health display (seconds of history); this
    # evaluation runs for hours, so it is swapped for a much larger one to keep every sample.
    source.poller.latency_ms = deque(maxlen=2_000_000)
    engine = LiveEngine(loaded, load_baseline(d), graph, settings, source, detector_kind=kind)
    check_host(cfg.host, settings.attacker_allowlist)  # fail fast, before anything connects
    attacker = AttackerClient(cfg.host, cfg.port, tagmap, settings.attacker_allowlist)
    await source.start()
    if not await attacker.connect():
        raise SystemExit(f"attacker could not connect to {cfg.host}:{cfg.port}")
    for _ in range(100):
        if source.ready:
            break
        await asyncio.sleep(0.2)
    if not source.ready:
        raise SystemExit("LIVE source never became ready")
    return LiveEvalState(engine, source, attacker)


async def run(
    settings: Settings, clean_minutes: float, seeds: range, skip_clean: bool, skip_attacks: bool
) -> dict[str, object]:
    state = await build_state(settings)
    t_start = time.time()
    try:
        if not skip_clean:
            log.info("clean session: %.0f min", clean_minutes)
            await state.run_quiet(clean_minutes * 60.0)
        results: list[AttackResult] = []
        if not skip_attacks:
            specs = [
                (sc, *_spec(seed, sc)) for sc in Scenario for seed in seeds
            ]  # (scenario, target, magnitude)
            for i, (sc, target, magnitude) in enumerate(specs, start=1):
                log.info("attack %d/%d: %s on %s", i, len(specs), sc.value, target)
                results.append(await state.run_attack(sc, target, magnitude))
        return _summarize(state, results, time.time() - t_start)
    finally:
        await state.attacker.close()
        await state.source.stop()


def _spec(seed: int, scenario: Scenario) -> tuple[str, float]:
    spec = sample_attack(np.random.default_rng(30_000 + seed), scenario)
    return spec.target, spec.magnitude


def _summarize(
    state: LiveEvalState, results: list[AttackResult], uptime_s: float
) -> dict[str, object]:
    lat = list(state.source.poller.latency_ms)
    detected = [r for r in results if r.detected]
    per_scenario: dict[str, dict[str, object]] = {}
    for sc in Scenario:
        rs = [r for r in results if r.scenario == sc.value]
        if not rs:
            continue
        per_scenario[sc.value] = {
            "n": len(rs),
            "detected": sum(r.detected for r in rs),
            "top1": float(np.mean([r.top1 for r in rs])),
            "top3": float(np.mean([r.top3 for r in rs])),
        }
    return {
        "detection": {
            **_prf(state.samples),
            "false_alarm_per_hour": _false_alarm_per_hour(state.samples),
        },
        "localization": {
            "top1": float(np.mean([r.top1 for r in results])) if results else 0.0,
            "top3": float(np.mean([r.top3 for r in results])) if results else 0.0,
            "top1_given_detected": float(np.mean([r.top1 for r in detected])) if detected else None,
            "top3_given_detected": float(np.mean([r.top3 for r in detected])) if detected else None,
            "mean_time_to_localize_s": float(np.mean([r.time_to_localize_s for r in detected]))
            if detected
            else None,
            "mean_detection_delay_s": float(
                np.mean([r.detection_delay_s for r in detected if r.detection_delay_s is not None])
            )
            if any(r.detection_delay_s is not None for r in detected)
            else None,
        },
        "latency_ms": {"p50": _pct(lat, 0.50), "p95": _pct(lat, 0.95), "p99": _pct(lat, 0.99)},
        "latency_note": (
            "Modbus read round-trip per poll: the dominant, directly measurable freshness cost. "
            "Excludes the up-to-poll-interval wait for a changed value and browser rendering "
            "(this evaluation has no browser client)."
        ),
        "samples_per_s": state.source.aligner.accepted / uptime_s if uptime_s > 0 else 0.0,
        "dropped": state.source.aligner.dropped_out_of_order,
        "n_attacks": len(results),
        "n_detected": len(detected),
        "n_clean_runs": 1,
        "uptime_s": uptime_s,
        "attacks": [vars(r) for r in results],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clean-min", type=float, default=DEFAULT_CLEAN_MIN)
    ap.add_argument("--attacks-per-scenario", type=int, default=len(LIVE_TEST_SEEDS))
    ap.add_argument("--skip-clean", action="store_true")
    ap.add_argument("--skip-attacks", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    seeds = list(LIVE_TEST_SEEDS)[: args.attacks_per_scenario]
    settings = get_settings()
    seed_range = range(seeds[0], seeds[-1] + 1)
    result = asyncio.run(
        run(settings, args.clean_min, seed_range, args.skip_clean, args.skip_attacks)
    )
    out = Path(args.out) if args.out else settings.reports_dir / "live_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    d = result["detection"]
    loc = result["localization"]
    assert isinstance(d, dict) and isinstance(loc, dict)
    log.info(
        "wrote %s: F1=%.3f FA/h=%.2f Top-1=%.2f Top-3=%.2f p95=%.1fms",
        out,
        d["f1"],
        d["false_alarm_per_hour"],
        loc["top1"],
        loc["top3"],
        result["latency_ms"]["p95"],  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
