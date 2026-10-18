"""Seeded SIM runs sampled at the detector rate, with random attack sampling and labels."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.attacks import AttackEngine, AttackSpec, GroundTruth, Scenario
from app.attacks.engine import VALID_TARGETS
from app.sim import NODE_IDS, Plant
from app.sim.topology import NODE_BY_ID

F64 = NDArray[np.float64]

EMIT_EVERY = 5  # plant ticks per detector sample: 10 Hz → 2 Hz (matches the WS emit rate)
SAMPLE_HZ = 2.0
RUN_S = 300.0
ATTACK_START_S = (90.0, 110.0)
ATTACK_DURATION_S = 120.0
RECOVERY_S = 60.0  # post-attack samples excluded from scoring (effects linger)


@dataclass(frozen=True)
class Run:
    seed: int
    t: F64  # (T,) plant seconds
    x: F64  # (T, 9) reported values, columns follow NODE_IDS
    truth: GroundTruth | None

    def labels(self) -> NDArray[np.int8]:
        """1 = attack active, 0 = normal, -1 = ignored (recovery after the attack)."""
        y = np.zeros(len(self.t), dtype=np.int8)
        if self.truth is not None:
            y[(self.t >= self.truth.start_s) & (self.t < self.truth.end_s)] = 1
            y[(self.t >= self.truth.end_s) & (self.t < self.truth.end_s + RECOVERY_S)] = -1
        return y


def simulate(seed: int, seconds: float = RUN_S, spec: AttackSpec | None = None) -> Run:
    engine = AttackEngine()
    truth = None
    if spec is not None:
        engine.schedule(spec)
        (truth,) = engine.ground_truth()
    plant = Plant(seed=seed, overlay=engine, track_impact=False)
    n = round(seconds / (plant.params.dt * EMIT_EVERY))
    ts = np.zeros(n)
    xs = np.zeros((n, len(NODE_IDS)))
    for i in range(n):
        for _ in range(EMIT_EVERY):
            plant.step()
        s = plant.state()
        ts[i] = plant.t
        xs[i] = [s[k] for k in NODE_IDS]
    return Run(seed, ts, xs, truth)


def sample_attack(rng: np.random.Generator, scenario: Scenario) -> AttackSpec:
    """Random attack of one scenario; magnitudes scale with the target's range."""
    targets = VALID_TARGETS[scenario]
    target = targets[int(rng.integers(len(targets)))]
    node = NODE_BY_ID[target]
    span = node.hi - node.lo
    sign = 1.0 if rng.random() < 0.5 else -1.0
    start = float(rng.uniform(*ATTACK_START_S))
    if scenario is Scenario.SENSOR_OFFSET:
        mag = sign * float(rng.uniform(0.15, 0.30)) * span
    elif scenario is Scenario.SENSOR_RAMP:
        mag = sign * float(rng.uniform(0.20, 0.40)) * span
    elif scenario is Scenario.ACTUATOR_FORCE:
        mag = float(rng.integers(2))
    elif scenario is Scenario.ROGUE_SETPOINT:
        mag = sign * float(rng.uniform(15.0, 30.0))
    else:
        mag = 0.0
    return AttackSpec(scenario, target, start, ATTACK_DURATION_S, mag)


def attack_run(seed: int, scenario: Scenario) -> Run:
    rng = np.random.default_rng(10_000 + seed)
    return simulate(seed, spec=sample_attack(rng, scenario))
