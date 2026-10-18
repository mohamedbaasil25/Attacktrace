"""Print simulated plant state.  `python -m app.sim.cli --seconds 30 [--attack ...]`."""

import argparse
import sys

from app.attacks import AttackEngine, AttackSpec, Scenario
from app.sim.plant import Plant
from app.sim.topology import NODE_IDS


def _fmt_eta(x: float | None) -> str:
    return "-" if x is None else f"{x:.0f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AttackTrace plant simulator")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--every", type=float, default=1.0, help="print period (s)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--attack", choices=[s.value for s in Scenario])
    ap.add_argument("--target", default="LIT101")
    ap.add_argument("--start", type=float, default=10.0)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--magnitude", type=float, default=-20.0)
    args = ap.parse_args(argv)

    engine = AttackEngine()
    if args.attack:
        engine.schedule(
            AttackSpec(
                Scenario(args.attack), args.target, args.start, args.duration, args.magnitude
            )
        )
    plant = Plant(seed=args.seed, overlay=engine)
    stride = max(1, round(args.every / plant.params.dt))
    steps = round(args.seconds / plant.params.dt)

    header = ["t_s", *NODE_IDS, "atk", "T1ovf_s", "T2dry_s", "kWh_w"]
    print(" ".join(f"{h:>8}" for h in header))
    for k in range(1, steps + 1):
        plant.step()
        if k % stride:
            continue
        s, im = plant.state(), plant.impact()
        atk = engine.active(plant.t)
        cells = [
            f"{plant.t:8.1f}",
            *(f"{s[n]:8.3f}" for n in NODE_IDS),
            f"{(atk[0].target if atk else '-'):>8}",
            f"{_fmt_eta(im.t1_overflow_s):>8}",
            f"{_fmt_eta(im.t2_dry_s):>8}",
            f"{im.energy_wasted_kwh:8.4f}",
        ]
        print(" ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
