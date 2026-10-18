"""Seeded 3-stage water-treatment plant: T1 → transfer pump → filter → T2 → outlet pump.

Units: tank levels in %, flow in L/s, pressure in bar, actuators in [0, 1].
Controllers act on *reported* sensor values, so spoofing fools them; physical truth is kept
separately. When impact tracking is on, a clean shadow plant with the same seed runs in
lock-step to give a counterfactual for wasted energy.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from app.sim.overlay import NoOverlay, Overlay
from app.sim.pid import PID


@dataclass(frozen=True)
class PlantParams:
    dt: float = 0.1
    cap1_l: float = 1000.0
    cap2_l: float = 1000.0
    qin_max: float = 12.0
    q101_max: float = 10.0
    q301_max: float = 10.0
    sp1: float = 50.0
    sp2: float = 50.0
    actuator_tau_s: float = 1.0
    pump_kw: float = 2.2
    warmup_s: float = 120.0
    noise_level: float = 0.15
    noise_flow: float = 0.05
    noise_pressure: float = 0.003
    noise_actuator: float = 0.002


@dataclass
class Impact:
    t1_overflow_s: float | None
    t1_dry_s: float | None
    t2_overflow_s: float | None
    t2_dry_s: float | None
    pump_stress: dict[str, float] = field(default_factory=dict)
    energy_wasted_kwh: float = 0.0
    overflow_l: float = 0.0


_HORIZON_S = 300.0  # ETAs beyond 5 min are not reported
_RATE_EPS = 0.15  # %/s; normal level swings stay below this after smoothing
_RATE_TAU_S = 15.0
_BAND_LO, _BAND_HI = 40.0, 60.0  # ETAs only outside the normal operating band


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, x))


def _time_to(level: float, rate: float, target: float) -> float | None:
    if (target >= 100.0 and level >= 99.9) or (target <= 0.0 and level <= 0.1):
        return 0.0
    if target >= 100.0 and rate > _RATE_EPS and level >= _BAND_HI:
        eta = (100.0 - level) / rate
    elif target <= 0.0 and rate < -_RATE_EPS and level <= _BAND_LO:
        eta = level / -rate
    else:
        return None
    return eta if eta <= _HORIZON_S else None


class Plant:
    def __init__(
        self,
        seed: int = 42,
        params: PlantParams | None = None,
        overlay: Overlay | None = None,
        track_impact: bool = True,
    ) -> None:
        self.params = params or PlantParams()
        self.overlay: Overlay = overlay or NoOverlay()
        self._track_impact = track_impact
        self.reset(seed)

    # ------------------------------------------------------------------ lifecycle
    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = seed
        p = self.params
        self._rng = np.random.default_rng(self.seed)
        self._k = 0
        self._warmup_steps = round(p.warmup_s / p.dt)
        self.l1 = p.sp1
        self.l2 = p.sp2
        self.q201 = 5.0
        self.q_in = 5.0
        self.q_out = 5.0
        self.actual = {"MV101": 0.42, "P101": 0.6, "P301": 0.5}
        self.plc = {"PLC1": 0.42, "PLC2": 0.5}
        self.setpoints = {"PLC1": p.sp1, "PLC2": p.sp2}
        self._ou_supply = 0.0
        self._ou_demand = 0.0
        self._pid1 = PID(kp=0.03, ki=0.002, bias=0.42)
        self._pid2 = PID(kp=0.03, ki=0.002, bias=0.5)
        self._reported: dict[str, float] = {}
        self._rate1 = 0.0
        self._rate2 = 0.0
        self._stress = {"P101": 0.0, "P301": 0.0}
        self._power_kw = 0.0
        self.energy_kwh = 0.0
        self._wasted_kwh = 0.0
        self.overflow_l = 0.0
        self._shadow: Plant | None = None
        for _ in range(self._warmup_steps):
            self._advance()
        if self._track_impact:  # clean twin, same seed, already warmed up to t = 0
            self._shadow = Plant(self.seed, p, None, track_impact=False)
        # Impact accounting starts at t = 0.
        self.energy_kwh = 0.0
        self._wasted_kwh = 0.0
        self.overflow_l = 0.0
        self._stress = {"P101": 0.0, "P301": 0.0}

    @property
    def t(self) -> float:
        """Plant time in seconds; warm-up runs at t < 0."""
        return (self._k - self._warmup_steps) * self.params.dt

    def step(self) -> None:
        self._advance()

    # ------------------------------------------------------------------ views
    def state(self) -> dict[str, float]:
        """Values as reported to the controllers/SCADA (may be spoofed)."""
        return dict(self._reported)

    def physical_truth(self) -> dict[str, float]:
        return {
            "LIT101": self.l1,
            "MV101": self.actual["MV101"],
            "P101": self.actual["P101"],
            "FIT201": self.q201,
            "PIT301": self._pressure(),
            "LIT301": self.l2,
            "P301": self.actual["P301"],
            "PLC1": self.plc["PLC1"],
            "PLC2": self.plc["PLC2"],
        }

    def impact(self) -> Impact:
        return Impact(
            t1_overflow_s=_time_to(self.l1, self._rate1, 100.0),
            t1_dry_s=_time_to(self.l1, self._rate1, 0.0),
            t2_overflow_s=_time_to(self.l2, self._rate2, 100.0),
            t2_dry_s=_time_to(self.l2, self._rate2, 0.0),
            pump_stress=dict(self._stress),
            energy_wasted_kwh=self._wasted_kwh,
            overflow_l=self.overflow_l,
        )

    # ------------------------------------------------------------------ internals
    def _pressure(self) -> float:
        return 0.3 + 0.012 * self.q201**2 + 0.2 * self.l2 / 100.0

    def _advance(self) -> None:
        p = self.params
        dt = p.dt
        t = self.t
        ov = self.overlay
        noise = self._rng.normal(0.0, 1.0, size=9)

        # 1. Measure (honest reading + noise, then attacker overlay).
        truth = self.physical_truth()
        sigma = {
            "LIT101": p.noise_level,
            "FIT201": p.noise_flow,
            "PIT301": p.noise_pressure,
            "LIT301": p.noise_level,
        }
        rep: dict[str, float] = {}
        for i, sid in enumerate(("LIT101", "FIT201", "PIT301", "LIT301")):
            rep[sid] = ov.sensor(sid, truth[sid] + sigma[sid] * float(noise[i]), t)

        # 2. Controllers read reported values.
        sp1 = ov.setpoint("PLC1", p.sp1, t)
        sp2 = ov.setpoint("PLC2", p.sp2, t)
        self.setpoints = {"PLC1": sp1, "PLC2": sp2}
        u1 = self._pid1.update(sp1 - rep["LIT101"], dt)
        p101_cmd = _clip(0.6 + 0.02 * (rep["LIT101"] - sp1))
        u2 = self._pid2.update(rep["LIT301"] - sp2, dt)
        self.plc = {"PLC1": u1, "PLC2": u2}

        # 3. Actuators: overlay on command, then first-order lag.
        alpha = dt / p.actuator_tau_s
        for aid, cmd in (("MV101", u1), ("P101", p101_cmd), ("P301", u2)):
            target = _clip(ov.actuator(aid, cmd, t))
            self.actual[aid] += (target - self.actual[aid]) * alpha

        # 4. Disturbances (Ornstein-Uhlenbeck + slow periodic component).
        self._ou_supply += -self._ou_supply * dt / 20.0 + 0.05 * math.sqrt(dt) * float(noise[7])
        self._ou_demand += -self._ou_demand * dt / 20.0 + 0.05 * math.sqrt(dt) * float(noise[8])
        supply = _clip(1.0 + 0.15 * math.sin(2 * math.pi * t / 120.0) + self._ou_supply, 0.5, 1.5)
        demand = _clip(
            1.0 + 0.10 * math.sin(2 * math.pi * t / 90.0 + 1.0) + self._ou_demand, 0.5, 1.5
        )

        # 5. Physics: mass balance per tank.
        mv, p101, p301 = self.actual["MV101"], self.actual["P101"], self.actual["P301"]
        self.q_in = p.qin_max * mv * supply
        avail1 = _clip(self.l1 / 3.0)
        avail2 = _clip(self.l2 / 3.0)
        self.q201 = p.q101_max * p101 * avail1 * (1.0 - 0.3 * self.l2 / 100.0)
        self.q_out = p.q301_max * p301 * demand * avail2
        l1_prev, l2_prev = self.l1, self.l2
        self.l1 += (self.q_in - self.q201) * dt / p.cap1_l * 100.0
        self.l2 += (self.q201 - self.q_out) * dt / p.cap2_l * 100.0
        for name in ("l1", "l2"):
            level = getattr(self, name)
            cap = p.cap1_l if name == "l1" else p.cap2_l
            if level > 100.0:
                self.overflow_l += (level - 100.0) / 100.0 * cap
                level = 100.0
            setattr(self, name, max(0.0, level))

        # 6. Reported actuator feedback and controller outputs.
        for j, aid in enumerate(("MV101", "P101", "P301")):
            rep[aid] = self.actual[aid] + p.noise_actuator * float(noise[4 + j])
        rep["PLC1"], rep["PLC2"] = u1, u2
        self._reported = {k: rep[k] for k in truth}

        # 7. Impact bookkeeping.
        ew = dt / _RATE_TAU_S
        self._rate1 += ((self.l1 - l1_prev) / dt - self._rate1) * ew
        self._rate2 += ((self.l2 - l2_prev) / dt - self._rate2) * ew
        es = dt / 30.0
        for pid_, speed, avail in (("P101", p101, avail1), ("P301", p301, avail2)):
            bad = (avail < 1.0 and speed > 0.1) or speed > 0.98
            self._stress[pid_] += ((1.0 if bad else 0.0) - self._stress[pid_]) * es
        self._power_kw = p.pump_kw * (p101**3 + p301**3)
        self.energy_kwh += self._power_kw * dt / 3600.0
        self._k += 1
        if self._shadow is not None:
            self._shadow._advance()
            excess = max(0.0, self._power_kw - self._shadow._power_kw)
            self._wasted_kwh += excess * dt / 3600.0
