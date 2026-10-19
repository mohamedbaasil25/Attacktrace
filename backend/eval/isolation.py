"""Isolate-and-recover evaluation (Phase 11 B3) on the seeded held-out SIM attacks.

Each attack runs live through the engine: warm up, launch, wait for the incident to open, then
isolate one node and give the plant `TIMEOUT_S` of plant time to be declared contained. Three arms:
the Top-1 candidate (what an operator would click), the true origin (oracle), and a wrong node
(control: must never contain)."""

from dataclasses import dataclass

import networkx as nx
import numpy as np

from app.attacks import Scenario
from app.attacks.engine import AttackSpec
from app.config import Settings
from app.data.simdata import sample_attack
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.localize.incident import SAMPLE_DT
from app.schemas import AttackRequest
from eval.localization import TEST_ATTACK_SEEDS

TIMEOUT_S = 60.0  # plant seconds allowed after the isolate action
OPEN_WAIT = 200  # samples to wait for the incident to open after the launch


@dataclass(frozen=True)
class Arm:
    contained: bool
    time_s: float | None


def _spec(seed: int, scenario: Scenario) -> AttackSpec:
    return sample_attack(np.random.default_rng(10_000 + seed), scenario)


def _open_incident(engine: Engine, seed: int, spec: AttackSpec) -> tuple[str, list[str]] | None:
    """Reset, run to the attack's start, launch it, and return (incident id, top-3 ids) once the
    incident is open; None when it is never detected."""
    engine.reset(seed)
    for _ in range(round(spec.start_s / SAMPLE_DT)):
        engine.step_sample()
    engine.launch(
        AttackRequest(
            scenario=spec.scenario,
            target=spec.target,
            magnitude=spec.magnitude,
            duration_s=spec.duration_s,
        )
    )
    for _ in range(OPEN_WAIT):
        inc = engine.step_sample().incident
        if inc is not None and inc.status == "open":
            return inc.id, [o.id for o in inc.origin]
    return None


def _isolate(engine: Engine, inc_id: str, node: str) -> Arm:
    applied, _ = engine.isolate(inc_id, node)
    if not applied:
        return Arm(False, None)
    for _ in range(round(TIMEOUT_S / SAMPLE_DT)):
        inc = engine.step_sample().incident
        if inc is not None and inc.status == "contained":
            return Arm(True, inc.time_to_contain_s)
    return Arm(False, None)


def _summary(arms: list[Arm]) -> dict[str, object]:
    times = [a.time_s for a in arms if a.contained and a.time_s is not None]
    return {
        "n": len(arms),
        "contained": sum(a.contained for a in arms),
        "success_rate": sum(a.contained for a in arms) / len(arms) if arms else None,
        "mean_time_to_contain_s": float(np.mean(times)) if times else None,
    }


def run_isolation(
    loaded: Loaded, baseline: BaselineDetector, graph: nx.DiGraph, settings: Settings
) -> dict[str, object]:
    engine = Engine(loaded, baseline, graph, settings)
    top1: list[Arm] = []
    oracle: list[Arm] = []
    wrong: list[Arm] = []
    per: dict[str, list[Arm]] = {sc.value: [] for sc in Scenario}
    n_attacks = 0
    for sc in Scenario:
        for seed in TEST_ATTACK_SEEDS:
            n_attacks += 1
            spec = _spec(seed, sc)
            opened = _open_incident(engine, seed, spec)
            if opened is None:
                continue
            _, ranked = opened  # top-3 ids; the isolate arms below replay the identical run
            arm = _isolate(engine, opened[0], ranked[0])
            top1.append(arm)
            per[sc.value].append(arm)

            again = _open_incident(engine, seed, spec)
            assert again is not None  # deterministic replay of the same seed
            oracle.append(_isolate(engine, again[0], spec.target))

            again = _open_incident(engine, seed, spec)
            assert again is not None
            other = next((n for n in again[1] if n != spec.target), None)
            if other is not None:
                wrong.append(_isolate(engine, again[0], other))
    return {
        "n_attacks": n_attacks,
        "n_detected": len(top1),
        "contain_quiet_s": settings.contain_s,
        "timeout_s": TIMEOUT_S,
        "isolate_top1": _summary(top1),
        "isolate_true_origin": _summary(oracle),
        "isolate_wrong_node": _summary(wrong),
        "success_rate_all_attacks": sum(a.contained for a in top1) / n_attacks,
        "per_scenario_top1": {k: _summary(v) for k, v in per.items() if v},
    }


if __name__ == "__main__":
    import json

    from app.config import get_settings
    from app.detect.pipeline import load_baseline, load_detector
    from app.graph import load_graph

    cfg = get_settings()
    out = run_isolation(
        load_detector(cfg.models_dir),
        load_baseline(cfg.models_dir),
        load_graph(cfg.models_dir / "graph.json"),
        cfg,
    )
    print(json.dumps(out, indent=1))
