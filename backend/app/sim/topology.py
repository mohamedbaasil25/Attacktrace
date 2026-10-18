"""Plant node catalogue and static P&ID edges."""

from dataclasses import dataclass
from enum import StrEnum


class NodeType(StrEnum):
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    CONTROLLER = "controller"


@dataclass(frozen=True)
class NodeSpec:
    id: str
    type: NodeType
    label: str
    unit: str
    lo: float
    hi: float


NODES: tuple[NodeSpec, ...] = (
    NodeSpec("LIT101", NodeType.SENSOR, "Tank T1 level", "%", 0.0, 100.0),
    NodeSpec("MV101", NodeType.ACTUATOR, "T1 inlet valve", "open", 0.0, 1.0),
    NodeSpec("P101", NodeType.ACTUATOR, "Transfer pump", "speed", 0.0, 1.0),
    NodeSpec("FIT201", NodeType.SENSOR, "Filter flow", "L/s", 0.0, 12.0),
    NodeSpec("PIT301", NodeType.SENSOR, "Filter pressure", "bar", 0.0, 2.5),
    NodeSpec("LIT301", NodeType.SENSOR, "Tank T2 level", "%", 0.0, 100.0),
    NodeSpec("P301", NodeType.ACTUATOR, "T2 outlet pump", "speed", 0.0, 1.0),
    NodeSpec("PLC1", NodeType.CONTROLLER, "T1 controller", "out", 0.0, 1.0),
    NodeSpec("PLC2", NodeType.CONTROLLER, "T2 controller", "out", 0.0, 1.0),
)

NODE_IDS: tuple[str, ...] = tuple(n.id for n in NODES)
NODE_BY_ID: dict[str, NodeSpec] = {n.id: n for n in NODES}
SENSORS: tuple[str, ...] = tuple(n.id for n in NODES if n.type is NodeType.SENSOR)
ACTUATORS: tuple[str, ...] = tuple(n.id for n in NODES if n.type is NodeType.ACTUATOR)
CONTROLLERS: tuple[str, ...] = tuple(n.id for n in NODES if n.type is NodeType.CONTROLLER)

# Weak couplings that only matter at extremes (suction at near-empty tank, back-pressure).
# Propagation ordering treats them as slower than the main control/flow path.
SECONDARY_EDGES: frozenset[tuple[str, str]] = frozenset(
    {("LIT101", "FIT201"), ("LIT301", "FIT201"), ("LIT301", "PIT301")}
)

# Directed cause → effect edges from the P&ID (physical flow + control signals).
PID_EDGES: tuple[tuple[str, str], ...] = (
    ("LIT101", "PLC1"),  # level measurement into controller
    ("PLC1", "MV101"),  # PID output → inlet valve
    ("PLC1", "P101"),  # level-scheduled pump speed
    ("MV101", "LIT101"),  # inflow fills T1
    ("P101", "LIT101"),  # pumping drains T1
    ("P101", "FIT201"),  # pump drives filter flow
    ("LIT101", "FIT201"),  # suction availability
    ("FIT201", "PIT301"),  # flow → filter pressure drop
    ("FIT201", "LIT301"),  # flow fills T2
    ("LIT301", "PIT301"),  # T2 head → back-pressure
    ("LIT301", "FIT201"),  # back-pressure limits flow
    ("LIT301", "PLC2"),  # level measurement into controller
    ("PLC2", "P301"),  # PID output → outlet pump
    ("P301", "LIT301"),  # pumping drains T2
)
