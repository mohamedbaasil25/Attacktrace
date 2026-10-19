"""Phase 14 A8: sustainability / edge-impact measurements.

Model size and parameter count: read directly from the saved model files. Inference timing:
measured here (CPU, single thread, the already-trained model, no training). Peak RSS: sampled
during an in-process run of 600 ticks (5 minutes of SIMULATED plant time at 2 Hz, executed in
compressed wall time -- labelled as such, not a real-time 5-minute wall-clock run). CPU% at 2 Hz is
derived from the measured per-tick inference time against the 0.5 s tick period, not from a
real-time OS sampler. Impact with vs without containment: replays the same 50 held-out attacks
`eval/isolation.py` uses, once with the Top-1 isolate action and once with no action for the same
timeout, reading `Impact.energy_wasted_kwh` from each run -- in-process, no real-time pacing needed
since the simulator's tick does not block on a wall clock.
"""

import time
from pathlib import Path

import numpy as np
import torch

from app.attacks import Scenario
from app.config import Settings, get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.engine import Engine
from app.graph import load_graph
from app.localize.incident import SAMPLE_DT
from eval.analysis._util import merge_write
from eval.isolation import TIMEOUT_S, _isolate, _open_incident, _spec
from eval.live_soak import _rss_mb
from eval.localization import TEST_ATTACK_SEEDS


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def _model_stats(models_dir: Path, name: str) -> dict[str, object] | None:
    p = models_dir / f"{name}.pt"
    if not p.exists():
        return None
    state = torch.load(p, map_location="cpu", weights_only=True)
    n_params = sum(int(np.prod(v.shape)) for v in state.values() if hasattr(v, "shape"))
    return {"file": p.name, "size_bytes": p.stat().st_size, "n_params": n_params}


def _inference_timing(settings: Settings) -> dict[str, object]:
    loaded = load_detector(settings.models_dir)
    from app.data.simdata import simulate

    r = simulate(2000)  # one held-out clean run, already generated for the detection eval
    times: list[float] = []
    for i in range(10, len(r.x)):
        window = r.x[i - 10 : i + 1]  # the model's own 10-sample (5 s) lookback
        t0 = time.perf_counter()
        loaded.detector.score_run(window)
        times.append(time.perf_counter() - t0)
    return {
        "n_ticks": len(times),
        "mean_ms": float(np.mean(times)) * 1000,
        "p95_ms": _pct(times, 0.95) * 1000,
        "cpu_pct_at_2hz": float(np.mean(times)) / SAMPLE_DT * 100,
    }


def _peak_rss_over_simulated_run(settings: Settings) -> dict[str, object]:
    loaded = load_detector(settings.models_dir)
    baseline = load_baseline(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    engine = Engine(loaded, baseline, graph, settings)
    engine.reset(9001)
    samples: list[float | None] = []
    for i in range(600):  # 600 ticks @ 2 Hz = 5 simulated minutes, run in compressed wall time
        engine.step_sample()
        if i % 20 == 0:
            samples.append(_rss_mb())
    vals = [s for s in samples if s is not None]
    return {
        "n_ticks": 600,
        "n_rss_samples": len(vals),
        "peak_rss_mb": max(vals) if vals else None,
        "first_rss_mb": vals[0] if vals else None,
        "last_rss_mb": vals[-1] if vals else None,
        "note": "600 ticks = 5 minutes of SIMULATED plant time at 2 Hz, executed in a tight loop "
        "(compressed wall time, not a real-time 5-minute measurement).",
    }


def _impact_with_vs_without(settings: Settings) -> dict[str, object]:
    loaded = load_detector(settings.models_dir)
    baseline = load_baseline(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    engine = Engine(loaded, baseline, graph, settings)
    with_energy: list[float] = []
    without_energy: list[float] = []
    n_compared = 0
    for sc in Scenario:
        for seed in TEST_ATTACK_SEEDS:
            spec = _spec(seed, sc)
            opened = _open_incident(engine, seed, spec)
            if opened is None:
                continue
            inc_id, ranked = opened
            _isolate(engine, inc_id, ranked[0])
            msg = engine.step_sample()
            e_with = msg.impact.energy_wasted_kwh if msg.impact else 0.0

            again = _open_incident(engine, seed, spec)
            if again is None:
                continue
            for _ in range(round(TIMEOUT_S / SAMPLE_DT)):
                msg = engine.step_sample()
            e_without = msg.impact.energy_wasted_kwh if msg.impact else 0.0

            with_energy.append(e_with)
            without_energy.append(e_without)
            n_compared += 1
    return {
        "n_compared": n_compared,
        "mean_energy_wasted_kwh_with_top1_isolate": float(np.mean(with_energy))
        if with_energy
        else None,
        "mean_energy_wasted_kwh_without_action": float(np.mean(without_energy))
        if without_energy
        else None,
        "note": "energy_wasted_kwh as read from Impact at the moment isolate completes its "
        "timeout window (with) vs. the moment the no-action timeout window ends (without); both "
        "the simulator's own running estimate, not an external measurement.",
    }


def analyze() -> dict[str, object]:
    settings = get_settings()
    return {
        "model_gdn": _model_stats(settings.models_dir, "gdn"),
        "model_mlp": _model_stats(settings.models_dir, "mlp"),
        "inference_timing": _inference_timing(settings),
        "peak_rss": _peak_rss_over_simulated_run(settings),
        "impact_with_vs_without_containment": _impact_with_vs_without(settings),
    }


def main() -> int:
    result = analyze()
    out = merge_write("sustainability", result)
    it, rss = result["inference_timing"], result["peak_rss"]
    assert isinstance(it, dict) and isinstance(rss, dict)
    print(
        f"wrote {out}: inference mean={it['mean_ms']:.2f}ms p95={it['p95_ms']:.2f}ms "
        f"cpu%={it['cpu_pct_at_2hz']:.2f} peak_rss={rss['peak_rss_mb']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
