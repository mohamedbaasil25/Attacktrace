"""Register-backed attack overlay: whatever a Modbus client writes to the spoof, force and
setpoint registers acts on the emulated plant through the same `Overlay` hooks the simulator's
own attack engine uses. This is the emulated man-in-the-middle; the physics and the PLC loops
inside `Plant` react to it exactly as they do in SIM."""

from dataclasses import dataclass, field

from app.attacks.engine import SETPOINT_LIMITS


@dataclass
class Controls:
    """Current attack-surface register values, refreshed from the holding registers each tick."""

    offset: dict[str, float] = field(default_factory=dict)  # sensor -> added to its reading
    freeze: dict[str, bool] = field(default_factory=dict)  # sensor -> hold the last reading
    force: dict[str, float] = field(default_factory=dict)  # actuator -> forced command; <0 = none
    delta: dict[str, float] = field(default_factory=dict)  # controller -> setpoint delta


class RegisterOverlay:
    def __init__(self) -> None:
        self.controls = Controls()
        self._held: dict[str, float] = {}

    def sensor(self, node: str, value: float, t: float) -> float:
        if self.controls.freeze.get(node, False):
            value = self._held.setdefault(node, value)  # captured at the first frozen sample
        else:
            self._held.pop(node, None)
        return value + self.controls.offset.get(node, 0.0)

    def actuator(self, node: str, command: float, t: float) -> float:
        forced = self.controls.force.get(node, -1.0)
        return min(1.0, forced) if forced >= 0.0 else command

    def setpoint(self, node: str, value: float, t: float) -> float:
        delta = self.controls.delta.get(node, 0.0)
        if delta == 0.0:
            return value
        lo, hi = SETPOINT_LIMITS
        return min(hi, max(lo, value + delta))
