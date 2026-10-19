"""Production Readiness Roadmap: slow-drift evasion measurement.

`sensor_ramp` already drifts its target linearly to the full magnitude over the attack's
`duration_s` (see `AttackEngine.sensor`): a slow enough ramp is the natural analog of an
adversary trying to stay under the detector's radar by moving gradually instead of jumping.
This script launches the same ramp magnitude at a range of durations (seconds to tens of
minutes) and logs whether/when it's caught. `sensor_ramp` is the documented weakest held-out
scenario (sample recall 0.52), so it's the most informative one to stress here.

This is exploratory measurement, not a pass/fail gate: `python -m eval.evasion_slow_drift`.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import cast

from app.attacks import Scenario
from app.config import Settings, get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.engine import Engine
from app.graph import load_graph
from app.localize.incident import SAMPLE_DT
from app.schemas import AttackRequest

log = logging.getLogger("attacktrace.eval.evasion_slow_drift")

DEFAULT_RAMP_RATES_S = [30.0, 60.0, 120.0, 300.0, 600.0]
DEFAULT_TARGET = "LIT101"
DEFAULT_MAGNITUDE = -25.0  # same offset magnitude used elsewhere for this target
TAIL_S = 60.0  # extra plant time watched after the ramp nominally finishes


def _build_engine(settings: Settings) -> Engine:
    loaded = load_detector(settings.models_dir)
    baseline = load_baseline(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    return Engine(loaded, baseline, graph, settings)


def run_one(engine: Engine, ramp_s: float, target: str, magnitude: float) -> dict[str, object]:
    engine.reset()
    engine.launch(
        AttackRequest(
            scenario=Scenario.SENSOR_RAMP,
            target=target,
            magnitude=magnitude,
            duration_s=ramp_s,
        )
    )
    total_samples = round((ramp_s + TAIL_S) / SAMPLE_DT)
    detected_at: float | None = None
    opened_at: float | None = None
    final_status: str | None = None
    for k in range(total_samples):
        msg = engine.step_sample()
        t = k * SAMPLE_DT
        if msg.alert is not None and detected_at is None:
            detected_at = t
        if msg.incident is not None:
            final_status = msg.incident.status
            if msg.incident.status == "open" and opened_at is None:
                opened_at = t
    return {
        "ramp_s": ramp_s,
        "detected": detected_at is not None,
        "delay_s": (detected_at - ramp_s) if detected_at is not None else None,
        "opened": opened_at is not None,
        "time_to_open_s": (opened_at - ramp_s) if opened_at is not None else None,
        "final_status": final_status,
    }


def run(
    settings: Settings, ramp_rates: list[float], target: str, magnitude: float
) -> dict[str, object]:
    engine = _build_engine(settings)
    records = [run_one(engine, r, target, magnitude) for r in ramp_rates]
    return {
        "scenario": Scenario.SENSOR_RAMP.value,
        "target": target,
        "magnitude": magnitude,
        "records": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ramp-rates", default=",".join(str(r) for r in DEFAULT_RAMP_RATES_S))
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--magnitude", type=float, default=DEFAULT_MAGNITUDE)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    settings = get_settings()
    ramp_rates = [float(r) for r in str(args.ramp_rates).split(",")]
    result = run(settings, ramp_rates, args.target, args.magnitude)

    out = Path(args.out) if args.out else settings.reports_dir / "evasion_slow_drift.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))

    records = cast(list[dict[str, object]], result["records"])
    log.info("%-10s %-10s %-12s %s", "ramp_s", "detected", "delay_s", "final_status")
    for r in records:
        log.info(
            "%-10s %-10s %-12s %s",
            r["ramp_s"],
            r["detected"],
            r["delay_s"],
            r["final_status"],
        )
    log.info("wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
