"""The attacker's Modbus write client: schedules a scenario's register writes against an
emulator, clears them after `duration_s`, and records what it did (ground truth + audit log).

`sensor_ramp` is the only scenario that needs more than two writes: it steps the spoof offset
from 0 toward `magnitude` the same way the simulator's own overlay does (`frac = elapsed /
duration`, clamped to 1), once per `RAMP_STEP_S`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from pymodbus.client import AsyncModbusTcpClient

from app.attacks.engine import MITRE, VALID_TARGETS, Scenario
from app.live.tagmap import TagMap, encode, load_tagmap
from attacker.allowlist import check_host

log = logging.getLogger("attacktrace.attacker")

RAMP_STEP_S = 1.0
CONNECT_TIMEOUT_S = 3.0


class AttackerError(ValueError):
    """A request could not be scheduled (unknown target, bad magnitude, not connected)."""


@dataclass(frozen=True)
class AttackRecord:
    attack_id: str
    scenario: Scenario
    target: str
    magnitude: float
    duration_s: float
    start_wall: float
    mitre: str


def _surface_tag(scenario: Scenario, target: str) -> str:
    return {
        Scenario.SENSOR_OFFSET: f"{target}.spoof_offset",
        Scenario.SENSOR_RAMP: f"{target}.spoof_offset",
        Scenario.SENSOR_FREEZE: f"{target}.spoof_freeze",
        Scenario.ACTUATOR_FORCE: f"{target}.force",
        Scenario.ROGUE_SETPOINT: f"{target}.setpoint_delta",
    }[scenario]


def _neutral(scenario: Scenario) -> float:
    return -1.0 if scenario is Scenario.ACTUATOR_FORCE else 0.0


@dataclass
class AttackerClient:
    """Connect once, launch scenarios, clear them on schedule. Not reusable after `close()`."""

    host: str
    port: int
    tagmap: TagMap
    allowlist: str = ""
    timeout_s: float = CONNECT_TIMEOUT_S
    launched: list[AttackRecord] = field(default_factory=list, init=False)
    _client: AsyncModbusTcpClient | None = field(default=None, init=False, repr=False)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        check_host(self.host, self.allowlist)  # never constructed pointed at a real target

    async def connect(self) -> bool:
        self._client = AsyncModbusTcpClient(self.host, port=self.port, timeout=self.timeout_s)
        return bool(await self._client.connect())

    @property
    def connected(self) -> bool:
        return self._client is not None and bool(self._client.connected)

    async def _write(self, tag_name: str, value: float) -> None:
        if self._client is None or not self._client.connected:
            raise AttackerError("not connected to the emulator")
        tag = self.tagmap.get(tag_name)
        r = await self._client.write_registers(
            tag.address, encode(tag, value), device_id=self.tagmap.device_id
        )
        if r.isError():
            raise AttackerError(f"write to {tag_name} failed: {r}")
        log.info("attacker write tag=%s value=%s", tag_name, value)

    def validate(self, scenario: Scenario, target: str, magnitude: float) -> None:
        if target not in VALID_TARGETS[scenario]:
            allowed = ", ".join(VALID_TARGETS[scenario])
            raise AttackerError(f"{scenario} cannot target {target}; allowed: {allowed}")
        if scenario is Scenario.ACTUATOR_FORCE and not 0.0 <= magnitude <= 1.0:
            raise AttackerError("actuator_force magnitude must be in [0, 1]")

    async def launch(
        self, scenario: Scenario, target: str, magnitude: float, duration_s: float
    ) -> str:
        self.validate(scenario, target, magnitude)
        if duration_s <= 0:
            raise AttackerError("duration_s must be > 0")
        self._counter += 1
        attack_id = f"atk_{self._counter:03d}"
        tag = _surface_tag(scenario, target)
        start = time.time()
        if scenario is Scenario.SENSOR_FREEZE:
            await self._write(tag, 1)
        elif scenario is Scenario.SENSOR_RAMP:
            await self._write(tag, 0.0)
        else:
            await self._write(tag, magnitude)
        rec = AttackRecord(
            attack_id, scenario, target, magnitude, duration_s, start, MITRE[scenario]
        )
        self.launched.append(rec)
        log.info(
            "attacker launch id=%s scenario=%s target=%s magnitude=%s duration_s=%s",
            attack_id, scenario.value, target, magnitude, duration_s,
        )  # fmt: skip
        self._tasks.append(asyncio.create_task(self._run(rec, tag)))
        return attack_id

    async def _run(self, rec: AttackRecord, tag: str) -> None:
        try:
            if rec.scenario is Scenario.SENSOR_RAMP:
                elapsed = 0.0
                while elapsed < rec.duration_s:
                    await asyncio.sleep(min(RAMP_STEP_S, rec.duration_s - elapsed))
                    elapsed = time.time() - rec.start_wall
                    frac = min(1.0, elapsed / rec.duration_s)
                    await self._write(tag, rec.magnitude * frac)
            else:
                await asyncio.sleep(rec.duration_s)
            await self._write(tag, _neutral(rec.scenario))
            log.info(
                "attacker clear id=%s scenario=%s target=%s",
                rec.attack_id,
                rec.scenario.value,
                rec.target,
            )
        except asyncio.CancelledError:
            raise
        except AttackerError:
            log.exception("attacker could not clear id=%s", rec.attack_id)

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._client is not None:
            self._client.close()
            self._client = None


def load_attacker(tagmap_path: str, host: str, port: int, allowlist: str = "") -> AttackerClient:
    return AttackerClient(host, port, load_tagmap(tagmap_path), allowlist)
