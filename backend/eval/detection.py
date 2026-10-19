"""Detection evaluation on held-out seeded SIM runs: AttackTrace vs baseline."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.attacks import Scenario
from app.data.simdata import SAMPLE_HZ, Run, attack_run, simulate
from app.detect.baseline import BaselineDetector
from app.detect.detector import ForecastDetector, aggregate, alert_mask

TEST_ATTACK_SEEDS = range(1000, 1010)  # per scenario
TEST_CLEAN_SEEDS = range(2000, 2020)

Alerts = Callable[[Run], NDArray[np.bool_]]


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, alert: NDArray[np.bool_], y: NDArray[np.int8]) -> None:
        self.tp += int(np.sum(alert & (y == 1)))
        self.fp += int(np.sum(alert & (y == 0)))
        self.fn += int(np.sum(~alert & (y == 1)))

    def prf(self) -> dict[str, float]:
        p = self.tp / max(self.tp + self.fp, 1)
        r = self.tp / max(self.tp + self.fn, 1)
        return {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-12)}


def _onsets(alert: NDArray[np.bool_]) -> int:
    return int(np.sum(alert[1:] & ~alert[:-1]) + int(alert[0]))


def evaluate(name: str, alerts: Alerts, attacks: list[Run], clean: list[Run]) -> dict[str, object]:
    total = Counts()
    per: dict[str, Counts] = {sc.value: Counts() for sc in Scenario}
    detected: dict[str, list[bool]] = {sc.value: [] for sc in Scenario}
    delays: list[float] = []
    for r in attacks:
        assert r.truth is not None
        a, y = alerts(r), r.labels()
        total.add(a, y)
        per[r.truth.scenario.value].add(a, y)
        hit = np.flatnonzero(a & (y == 1))
        detected[r.truth.scenario.value].append(hit.size > 0)
        if hit.size:
            delays.append(float(r.t[hit[0]] - r.truth.start_s))
    clean_alerts = [alerts(r) for r in clean]
    clean_hours = sum(len(r.t) for r in clean) / SAMPLE_HZ / 3600.0
    for r, a in zip(clean, clean_alerts, strict=True):
        total.add(a, r.labels())
    return {
        "detector": name,
        **total.prf(),
        "false_alarm_per_hour": sum(_onsets(a) for a in clean_alerts) / clean_hours,
        "clean_alert_rate": float(np.mean(np.concatenate(clean_alerts))),
        "mean_detection_delay_s": float(np.mean(delays)) if delays else None,
        "per_scenario": {
            k: {**per[k].prf(), "runs_detected": float(np.mean(v)) if v else 0.0}
            for k, v in detected.items()
        },
    }


def run_detection(det: ForecastDetector, thr: float, base: BaselineDetector) -> dict[str, object]:
    attacks = [attack_run(s, sc) for sc in Scenario for s in TEST_ATTACK_SEEDS]
    clean = [simulate(s) for s in TEST_CLEAN_SEEDS]
    return {
        "attacktrace": evaluate(
            "forecaster", lambda r: alert_mask(aggregate(det.score_run(r.x)), thr), attacks, clean
        ),
        "baseline": evaluate("iforest+3sigma", lambda r: base.alert(r.x), attacks, clean),
        "n_attack_runs": len(attacks),
        "n_clean_runs": len(clean),
        "threshold": thr,
    }
