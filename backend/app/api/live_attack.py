"""Orchestrates `POST /api/attack` in LIVE mode: calls the attacker module (the only writer in
the project) and records the resulting ground truth on the running `LiveEngine`, purely for the
UI's "reveal". Kept out of `app/live/`, which stays strictly read-only toward the plant (see
`tests/test_live_connectors.py::test_the_live_package_has_no_write_path`); this module is the
seam the architecture diagram shows between the backend and the emulator-only `attacker/` tool.
"""

import sys
from pathlib import Path

try:
    import attacker  # noqa: F401
except ModuleNotFoundError:
    # Local dev: this file lives at backend/app/api/live_attack.py and `attacker/` is a sibling
    # of `backend/` (the repo root), four levels up. Docker sets PYTHONPATH to cover this; pytest
    # covers it via pyproject's `pythonpath`. This is the fallback for a plain `uvicorn
    # app.main:app` started from `backend/` without either of those.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from attacker.client import AttackerClient

from app.attacks import MITRE, GroundTruth, Scenario
from app.live.runtime import LiveRuntime
from app.schemas import AttackRequest
from app.sim.topology import NODE_BY_ID


class LiveAttackLauncher:
    def __init__(self, allowlist: str) -> None:
        self.allowlist = allowlist
        self.attacker: AttackerClient | None = None

    async def _ensure(self, rt: LiveRuntime) -> AttackerClient:
        if self.attacker is None:
            self.attacker = AttackerClient(rt.cfg.host, rt.cfg.port, rt.tagmap, self.allowlist)
        if not self.attacker.connected and not await self.attacker.connect():
            raise ValueError(f"attacker could not connect to {rt.cfg.host}:{rt.cfg.port}")
        return self.attacker

    async def launch(self, rt: LiveRuntime, req: AttackRequest) -> str:
        """The UI's attack button in LIVE mode: the attacker tool writes to the emulator, and the
        resulting ground truth is handed to the engine purely for the "reveal" UI; nothing here
        causes anything by itself beyond what the attacker already wrote."""
        if rt.engine is None:
            raise ValueError("LIVE is calibrating: no detector is running yet")
        scenario = Scenario(req.scenario)
        atk = await self._ensure(rt)
        attack_id = await atk.launch(scenario, req.target, req.magnitude, req.duration_s)
        now = rt.engine._source_t()
        gt = GroundTruth(
            attack_id=attack_id,
            scenario=scenario,
            target=req.target,
            origin_type=NODE_BY_ID[req.target].type,
            start_s=now,
            end_s=now + req.duration_s,
            magnitude=req.magnitude,
            mitre=MITRE[scenario],
        )
        rt.engine.record_external_launch(gt, rt.clock_now())
        return attack_id

    async def close(self) -> None:
        if self.attacker is not None:
            await self.attacker.close()
