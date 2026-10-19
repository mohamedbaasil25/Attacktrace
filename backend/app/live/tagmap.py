"""Tag map: which Modbus register holds which plant tag. One file (`config/tagmap.yaml`) feeds
the emulator, the live connectors and the attacker tool, so they cannot disagree.

Words and bytes are big-endian (float32 = 2 registers, high word first). `engineering = raw*scale`.
"""

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.sim.topology import ACTUATORS, CONTROLLERS, NODE_IDS, SENSORS

Role = Literal["value", "spoof_offset", "spoof_freeze", "force", "setpoint_delta"]
Table = Literal["input", "holding"]
Type = Literal["float32", "int16"]

WIDTH: dict[str, int] = {"float32": 2, "int16": 1}
ROLE_NODES: dict[str, tuple[str, ...]] = {
    "value": NODE_IDS,
    "spoof_offset": SENSORS,
    "spoof_freeze": SENSORS,
    "force": ACTUATORS,
    "setpoint_delta": CONTROLLERS,
}


class TagMapError(ValueError):
    """The tag map is invalid; the message names the tag and the rule."""


class Tag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str
    node_id: str
    protocol: Literal["modbus"]
    table: Table
    address: int
    type: Type
    scale: float = 1.0
    unit: str
    access: Literal["ro", "rw"]
    min: float
    max: float
    role: Role

    @property
    def width(self) -> int:
        return WIDTH[self.type]

    @model_validator(mode="after")
    def _check(self) -> "Tag":
        if not 0 <= self.address <= 65535 - self.width:
            raise ValueError(f"{self.tag}: address {self.address} outside 0..65535")
        if self.scale == 0:
            raise ValueError(f"{self.tag}: scale must not be 0")
        if not self.min < self.max:
            raise ValueError(f"{self.tag}: min must be below max")
        if self.node_id not in ROLE_NODES[self.role]:
            raise ValueError(f"{self.tag}: role {self.role} does not apply to {self.node_id}")
        if (self.role == "value") != (self.table == "input"):
            raise ValueError(f"{self.tag}: only role 'value' lives in the input registers")
        if (self.table == "input") != (self.access == "ro"):
            raise ValueError(f"{self.tag}: input registers are ro, holding registers rw")
        if self.role in ("spoof_freeze",) and self.type != "int16":
            raise ValueError(f"{self.tag}: spoof_freeze is an int16 flag")
        return self


class TagMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    device_id: int = 1
    tags: list[Tag]

    @model_validator(mode="after")
    def _check(self) -> "TagMap":
        names = [t.tag for t in self.tags]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"duplicate tag names: {sorted(dup)}")
        for table in ("input", "holding"):
            used: dict[int, str] = {}
            for t in self.tags:
                if t.table != table:
                    continue
                for a in range(t.address, t.address + t.width):
                    if a in used:
                        raise ValueError(f"{t.tag} overlaps {used[a]} at {table} register {a}")
                    used[a] = t.tag
        values = {t.node_id for t in self.tags if t.role == "value"}
        missing = [n for n in NODE_IDS if n not in values]
        if missing:
            raise ValueError(f"no value tag for nodes {missing}")
        keys = [(t.role, t.node_id) for t in self.tags]
        if len(set(keys)) != len(keys):
            raise ValueError("a role may appear once per node")
        return self

    def by_role(self, role: Role) -> list[Tag]:
        return [t for t in self.tags if t.role == role]

    def get(self, tag: str) -> Tag:
        for t in self.tags:
            if t.tag == tag:
                return t
        raise KeyError(tag)

    def surface(self, role: Role, node_id: str) -> Tag:
        """The attack-surface tag of a node, e.g. ("force", "P101")."""
        for t in self.tags:
            if t.role == role and t.node_id == node_id:
                return t
        raise KeyError(f"{role}:{node_id}")

    def size(self, table: Table) -> int:
        """Registers needed to cover every tag of a table."""
        return max((t.address + t.width for t in self.tags if t.table == table), default=0)

    def blocks(
        self, table: Table, max_gap: int = 8, max_len: int = 100
    ) -> Iterator[tuple[int, int]]:
        """Contiguous (start, count) register ranges covering the table's tags, for batched reads.
        Neighbouring tags closer than `max_gap` registers share one request (up to `max_len`)."""
        spans = sorted((t.address, t.address + t.width) for t in self.tags if t.table == table)
        start = end = None
        for lo, hi in spans:
            if start is None or end is None:
                start, end = lo, hi
            elif lo - end <= max_gap and hi - start <= max_len:
                end = max(end, hi)
            else:
                yield start, end - start
                start, end = lo, hi
        if start is not None and end is not None:
            yield start, end - start


def load_tagmap(path: Path | str) -> TagMap:
    """Read and validate the tag map; raises TagMapError with a readable message."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TagMapError(f"cannot read tag map {p}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TagMapError(f"tag map {p} is not valid YAML: {exc}") from exc
    try:
        return TagMap.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise TagMapError(f"tag map {p}: {where}: {first['msg']}") from exc


# ---------------------------------------------------------------------------- encoding
def encode(tag: Tag, value: float) -> list[int]:
    """Engineering value -> raw 16-bit registers (big-endian)."""
    raw = value / tag.scale
    if tag.type == "float32":
        hi, lo = struct.unpack(">HH", struct.pack(">f", raw))
        return [hi, lo]
    return [round(raw) & 0xFFFF]


def decode(tag: Tag, regs: list[int]) -> float:
    """Raw registers -> engineering value."""
    if tag.type == "float32":
        (raw,) = struct.unpack(">f", struct.pack(">HH", regs[0] & 0xFFFF, regs[1] & 0xFFFF))
        return float(raw) * tag.scale
    value = regs[0] & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value * tag.scale
