"""Attack scenario engine. Implements the `Overlay` hooks and records ground truth."""

from dataclasses import dataclass, field
from enum import StrEnum

from app.sim.topology import ACTUATORS, CONTROLLERS, NODE_BY_ID, SENSORS, NodeType


class Scenario(StrEnum):
    SENSOR_FREEZE = "sensor_freeze"
    SENSOR_OFFSET = "sensor_offset"
    SENSOR_RAMP = "sensor_ramp"
    ACTUATOR_FORCE = "actuator_force"
    ROGUE_SETPOINT = "rogue_setpoint"


MITRE: dict[Scenario, str] = {
    Scenario.SENSOR_FREEZE: "T0856",
    Scenario.SENSOR_OFFSET: "T0856",
    Scenario.SENSOR_RAMP: "T0856",
    Scenario.ACTUATOR_FORCE: "T0831",
    Scenario.ROGUE_SETPOINT: "T0855",
}

MITRE_NAME: dict[str, str] = {
    "T0856": "Spoof Reporting Message",
    "T0831": "Manipulation of Control",
    "T0855": "Unauthorized Command Message",
}

VALID_TARGETS: dict[Scenario, tuple[str, ...]] = {
    Scenario.SENSOR_FREEZE: SENSORS,
    Scenario.SENSOR_OFFSET: SENSORS,
    Scenario.SENSOR_RAMP: SENSORS,
    Scenario.ACTUATOR_FORCE: ACTUATORS,
    Scenario.ROGUE_SETPOINT: CONTROLLERS,
}

SETPOINT_LIMITS = (5.0, 95.0)


@dataclass(frozen=True)
class AttackSpec:
    """`magnitude` meaning: offset → bias (sensor units); ramp → drift reached at end;
    actuator_force → forced command in [0, 1]; rogue_setpoint → setpoint delta (%);
    freeze → ignored."""

    scenario: Scenario
    target: str
    start_s: float
    duration_s: float
    magnitude: float = 0.0


@dataclass(frozen=True)
class GroundTruth:
    attack_id: str
    scenario: Scenario
    target: str
    origin_type: NodeType
    start_s: float
    end_s: float
    magnitude: float
    mitre: str


@dataclass
class _Active:
    truth: GroundTruth
    frozen: float | None = None


@dataclass
class AttackEngine:
    _attacks: list[_Active] = field(default_factory=list)
    _counter: int = 0
    isolated: set[str] = field(default_factory=set)  # nodes the operator has isolated

    def schedule(self, spec: AttackSpec) -> str:
        scenario = Scenario(spec.scenario)
        if spec.target not in VALID_TARGETS[scenario]:
            allowed = ", ".join(VALID_TARGETS[scenario])
            raise ValueError(f"{scenario} cannot target {spec.target}; allowed: {allowed}")
        if spec.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if scenario is Scenario.ACTUATOR_FORCE and not 0.0 <= spec.magnitude <= 1.0:
            raise ValueError("actuator_force magnitude must be in [0, 1]")
        self._counter += 1
        attack_id = f"atk_{self._counter:03d}"
        truth = GroundTruth(
            attack_id=attack_id,
            scenario=scenario,
            target=spec.target,
            origin_type=NODE_BY_ID[spec.target].type,
            start_s=spec.start_s,
            end_s=spec.start_s + spec.duration_s,
            magnitude=spec.magnitude,
            mitre=MITRE[scenario],
        )
        self._attacks.append(_Active(truth))
        return attack_id

    def clear(self) -> None:
        self._attacks.clear()
        self._counter = 0
        self.isolated.clear()

    def isolate(self, node: str) -> None:
        """Defender action. An isolated sensor reports its honest reading (a redundant estimate),
        an isolated actuator follows its controller again, an isolated controller reverts to its
        authorized setpoint. The plant and the attack record are untouched; a node that is not
        under attack behaves as before, so isolating the wrong node changes nothing."""
        self.isolated.add(node)

    def ground_truth(self) -> list[GroundTruth]:
        return [a.truth for a in self._attacks]

    def active(self, t: float) -> list[GroundTruth]:
        return [a.truth for a in self._attacks if a.truth.start_s <= t < a.truth.end_s]

    def _live(self, node: str, t: float) -> list[_Active]:
        return [
            a
            for a in self._attacks
            if a.truth.target == node and a.truth.start_s <= t < a.truth.end_s
        ]

    # ------------------------------------------------------------- Overlay hooks
    def sensor(self, node: str, value: float, t: float) -> float:
        # Drop the captured freeze value whenever the attack is not live, so a plant
        # reset (time rewinds) or a finished attack never leaks a stale reading.
        for a in self._attacks:
            if a.truth.target == node and not a.truth.start_s <= t < a.truth.end_s:
                a.frozen = None
        if node in self.isolated:
            return value
        for a in self._live(node, t):
            gt = a.truth
            if gt.scenario is Scenario.SENSOR_FREEZE:
                if a.frozen is None:
                    a.frozen = value
                value = a.frozen
            elif gt.scenario is Scenario.SENSOR_OFFSET:
                value += gt.magnitude
            elif gt.scenario is Scenario.SENSOR_RAMP:
                frac = (t - gt.start_s) / (gt.end_s - gt.start_s)
                value += gt.magnitude * min(1.0, frac)
        return value

    def actuator(self, node: str, command: float, t: float) -> float:
        if node in self.isolated:
            return command
        for a in self._live(node, t):
            if a.truth.scenario is Scenario.ACTUATOR_FORCE:
                command = a.truth.magnitude
        return command

    def setpoint(self, node: str, value: float, t: float) -> float:
        if node in self.isolated:
            return value
        for a in self._live(node, t):
            if a.truth.scenario is Scenario.ROGUE_SETPOINT:
                lo, hi = SETPOINT_LIMITS
                value = min(hi, max(lo, value + a.truth.magnitude))
        return value
