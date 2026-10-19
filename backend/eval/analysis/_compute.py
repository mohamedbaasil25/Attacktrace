"""Shared read-only recomputation for Part A: forward-pass scoring with the already-trained,
already-frozen detector over the exact held-out seeds/files the committed metrics used. No
training, no weight/threshold change -- deterministic, so results are checked against the
committed aggregate as a consistency guard. Used by a4, a7 (and a8) to avoid re-deriving the same
forward pass more than once.
"""

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.attacks import Scenario
from app.config import get_settings
from app.data.hai import load_hai
from app.data.simdata import attack_run, simulate
from app.detect.detector import aggregate, alert_mask
from app.detect.hai_pipeline import TOP_K, load_hai_detector, split_tests
from app.detect.pipeline import load_detector
from eval.detection import TEST_ATTACK_SEEDS, TEST_CLEAN_SEEDS

F64 = NDArray[np.float64]


@dataclass
class SimForward:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    attack_delays: list[float] = field(default_factory=list)
    n_attacks: int = 0
    n_attacks_missed: int = 0


def sim_forward() -> SimForward:
    settings = get_settings()
    loaded = load_detector(settings.models_dir)
    out = SimForward()
    for sc in Scenario:
        for s in TEST_ATTACK_SEEDS:
            r = attack_run(s, sc)
            assert r.truth is not None
            a = alert_mask(aggregate(loaded.detector.score_run(r.x)), loaded.threshold)
            y = r.labels()
            out.tp += int(np.sum(a & (y == 1)))
            out.fp += int(np.sum(a & (y == 0)))
            out.fn += int(np.sum(~a & (y == 1)))
            out.n_attacks += 1
            hit = np.flatnonzero(a & (y == 1))
            if hit.size:
                out.attack_delays.append(float(r.t[hit[0]] - r.truth.start_s))
            else:
                out.n_attacks_missed += 1
    for s in TEST_CLEAN_SEEDS:
        r = simulate(s)
        a = alert_mask(aggregate(loaded.detector.score_run(r.x)), loaded.threshold)
        y = r.labels()
        out.tp += int(np.sum(a & (y == 1)))
        out.fp += int(np.sum(a & (y == 0)))
        out.fn += int(np.sum(~a & (y == 1)))
    return out


@dataclass
class HaiForward:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    window_delays: list[float] = field(default_factory=list)
    n_windows: int = 0
    n_windows_missed: int = 0


def hai_forward() -> HaiForward | None:
    settings = get_settings()
    if not (settings.models_dir / "hai" / "detector.json").exists():
        return None
    data = load_hai(settings.hai_dir)
    _tuning, held_out = split_tests(data)
    loaded = load_hai_detector(settings.models_dir)
    out = HaiForward()
    for f in held_out:
        alert = alert_mask(aggregate(loaded.detector.score_run(f.x), TOP_K), loaded.threshold)
        y = f.labels()
        ok = y >= 0  # -1 = recovery, excluded from P/R exactly as eval/hai.py does
        out.tp += int(np.sum(alert[ok] & (y[ok] == 1)))
        out.fp += int(np.sum(alert[ok] & (y[ok] == 0)))
        out.fn += int(np.sum(~alert[ok] & (y[ok] == 1)))
        for s, e in f.windows():
            out.n_windows += 1
            idx = np.flatnonzero(alert[s:e])
            if idx.size:
                out.window_delays.append(float(idx[0]))  # HAI is 1 Hz
            else:
                out.n_windows_missed += 1
    return out
