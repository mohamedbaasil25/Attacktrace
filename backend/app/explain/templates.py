"""Deterministic, template-based explanation: two short lines (what happened, what to do)."""

from dataclasses import dataclass

from app.attacks import MITRE_NAME
from app.sim.topology import NODE_BY_ID, NodeType

# Physical consequence of a node reading/acting HIGH or LOW relative to normal.
CONSEQUENCE: dict[str, dict[str, str]] = {
    "LIT101": {"low": "T1 overflow risk", "high": "T1 dry-run risk"},
    "LIT301": {"low": "T2 overflow risk", "high": "T2 dry-run risk"},
    "FIT201": {"low": "flow blind spot", "high": "flow blind spot"},
    "PIT301": {"low": "pressure blind spot", "high": "pressure blind spot"},
    "MV101": {"low": "T1 dry-run risk", "high": "T1 overflow risk"},
    "P101": {"low": "T1 overflow risk", "high": "T1 dry-run risk"},
    "P301": {"low": "T2 overflow risk", "high": "T2 dry-run risk"},
    "PLC1": {"low": "T1 dry-run risk", "high": "T1 overflow risk"},
    "PLC2": {"low": "T2 overflow risk", "high": "T2 dry-run risk"},
}

CONTROLLER_OF: dict[str, str] = {"LIT101": "PLC1", "LIT301": "PLC2"}  # sensors a PLC reads


@dataclass(frozen=True)
class Explanation:
    text: str
    action: str
    mitre: str
    mitre_name: str


def signature(node: str, direction: str, frozen: bool) -> tuple[str, str]:
    """(attack phrase, MITRE id) for an origin node seen high or low."""
    kind = NODE_BY_ID[node].type
    if kind is NodeType.SENSOR:
        return ("frozen" if frozen else f"spoof {direction}", "T0856")
    if kind is NodeType.ACTUATOR:
        word = {"MV101": ("open", "closed")}.get(node, ("on", "off"))
        return (f"forced {word[0] if direction == 'high' else word[1]}", "T0831")
    return (f"rogue setpoint ({direction} output)", "T0855")


def action_for(node: str) -> str:
    kind = NODE_BY_ID[node].type
    if kind is NodeType.SENSOR:
        plc = CONTROLLER_OF.get(node)
        return f"Isolate {node} · {plc} → manual" if plc else f"Isolate {node} · cross-check"
    if kind is NodeType.ACTUATOR:
        return f"Lock {node} · PLC → manual"
    return f"Isolate {node} · restore setpoint"


def explain(
    origin: str, direction: str, frozen: bool, downstream: list[str], max_chain: int = 2
) -> Explanation:
    phrase, mitre = signature(origin, direction, frozen)
    chain = " → ".join([*downstream[:max_chain], CONSEQUENCE[origin][direction]])
    kind = NODE_BY_ID[origin].type
    return Explanation(
        text=f"Origin {origin} ({kind}) · {phrase} → {chain}",
        action=action_for(origin),
        mitre=mitre,
        mitre_name=MITRE_NAME[mitre],
    )
