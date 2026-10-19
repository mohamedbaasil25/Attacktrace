"""Phase 14 C1: demo-reliability trials for 5 fixed (scenario, target, magnitude) demo click-paths
-- the exact ones a presenter would use -- run 30 times each, for SIM and for LIVE.

Measurement only: the trained model, thresholds and weights are untouched. SIM trials step the
`Engine` directly (no HTTP/WS), the same production code path `eval/isolation.py` already uses for
held-out evaluation -- fast, in-process, no real-time wait. LIVE trials reuse `eval.live`'s own
`LiveEvalState.run_attack` against the real emulator over real Modbus TCP, so they carry the same
real-time cost as `eval.live` itself (ATTACK_DURATION_S + GAP_S per trial): 150 LIVE trials take
roughly 8-9 hours.

    python -m eval.demo_trials --sim-only     # minutes
    python -m eval.demo_trials --live-only    # ~8-9 hours, needs the emulator running
    python -m eval.demo_trials                # both, SIM first

Writes reports/demo_trials.json and reports/demo_trials.md.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.attacks.engine import Scenario
from app.config import Settings, get_settings
from app.detect.pipeline import load_baseline, load_detector
from app.engine import Engine
from app.graph import load_graph
from app.localize.incident import SAMPLE_DT
from app.schemas import AttackRequest
from eval.live import build_state

log = logging.getLogger("attacktrace.eval.demo_trials")

# The 5 demo click-paths named in the Fix & Align prompt (Phase 14 C1), with the same magnitudes
# already used for these exact (scenario, target) pairs in submission/tools/rehearsal.py and
# Demo_Script.md -- these are not new choices, just reused ones.
PAIRS: list[tuple[Scenario, str, float]] = [
    (Scenario.SENSOR_OFFSET, "LIT101", -25.0),
    (Scenario.SENSOR_FREEZE, "LIT101", 0.0),
    (Scenario.ACTUATOR_FORCE, "MV101", 1.0),
    (Scenario.ROGUE_SETPOINT, "PLC1", 25.0),
    (Scenario.SENSOR_RAMP, "LIT301", 30.0),
]
N_TRIALS = 30


def pair_key(sc: Scenario, tg: str) -> str:
    return f"{sc.value}/{tg}"


# -------------------------------------------------------------------------------------------- SIM
SIM_SETTLE_S = 30.0  # matches the demo's own Reset -> wait 30s -> Launch click path
SIM_DURATION_S = 60.0  # matches the UI's default attack duration
SIM_OPEN_TIMEOUT_S = 90.0
SIM_CONTAIN_TIMEOUT_S = 60.0
SIM_SEED_BASE = 5000  # disjoint from every other seed range used in this project


@dataclass
class TrialResult:
    seed: int
    detected: bool
    detect_s: float | None
    localized_s: float | None
    top1: bool
    top3: bool
    ambiguous: bool | None
    origin_top3: list[str]
    rank: int | str | None
    contained: bool | None  # None: not attempted (not detected, or LIVE/read-only)
    time_to_contain_s: float | None
    latency_ms: float | None = None  # LIVE only: this trial's decision latency, if measured


def _rank(origin_ids: list[str], target: str, detected: bool) -> int | str | None:
    if target in origin_ids:
        return origin_ids.index(target) + 1
    return ">3" if detected else None


def run_sim_trial(
    engine: Engine, seed: int, scenario: Scenario, target: str, mag: float
) -> TrialResult:
    engine.reset(seed)
    for _ in range(round(SIM_SETTLE_S / SAMPLE_DT)):
        engine.step_sample()
    engine.launch(
        AttackRequest(scenario=scenario, target=target, magnitude=mag, duration_s=SIM_DURATION_S)
    )
    first_alert_i: int | None = None
    opened_i: int | None = None
    last_inc = None
    for i in range(round(SIM_OPEN_TIMEOUT_S / SAMPLE_DT)):
        msg = engine.step_sample()
        if msg.alert is not None and first_alert_i is None:
            first_alert_i = i
        if msg.incident is not None:
            last_inc = msg.incident
            if msg.incident.status == "open":
                opened_i = i
                break
    detected = last_inc is not None
    origin_ids = [o.id for o in last_inc.origin] if last_inc else []
    contained: bool | None = None
    time_to_contain: float | None = None
    if detected and opened_i is not None and origin_ids and last_inc is not None:
        accepted, _ = engine.isolate(last_inc.id, origin_ids[0])
        if accepted:
            contained = False
            for _ in range(round(SIM_CONTAIN_TIMEOUT_S / SAMPLE_DT)):
                msg = engine.step_sample()
                if msg.incident is not None and msg.incident.status == "contained":
                    contained = True
                    time_to_contain = msg.incident.time_to_contain_s
                    break
    return TrialResult(
        seed=seed,
        detected=detected,
        detect_s=first_alert_i * SAMPLE_DT if first_alert_i is not None else None,
        localized_s=opened_i * SAMPLE_DT if opened_i is not None else None,
        top1=bool(origin_ids and origin_ids[0] == target),
        top3=target in origin_ids[:3],
        ambiguous=last_inc.ambiguous if last_inc else None,
        origin_top3=origin_ids,
        rank=_rank(origin_ids, target, detected),
        contained=contained,
        time_to_contain_s=time_to_contain,
    )


def run_sim(settings: Settings, n_trials: int = N_TRIALS) -> dict[str, list[TrialResult]]:
    loaded = load_detector(settings.models_dir)
    baseline = load_baseline(settings.models_dir)
    graph = load_graph(settings.models_dir / "graph.json")
    engine = Engine(loaded, baseline, graph, settings)
    out: dict[str, list[TrialResult]] = {}
    for p_i, (sc, tg, mag) in enumerate(PAIRS):
        key = pair_key(sc, tg)
        rows = []
        for t_i in range(n_trials):
            seed = SIM_SEED_BASE + p_i * 100 + t_i
            row = run_sim_trial(engine, seed, sc, tg, mag)
            rows.append(row)
            log.info(
                "SIM  %-22s trial %2d/%d seed=%d detected=%s top1=%s contained=%s",
                key,
                t_i + 1,
                n_trials,
                seed,
                row.detected,
                row.top1,
                row.contained,
            )
        out[key] = rows
    return out


# ------------------------------------------------------------------------------------------- LIVE
async def run_live(settings: Settings, n_trials: int = N_TRIALS) -> dict[str, list[TrialResult]]:
    state = await build_state(settings)
    out: dict[str, list[TrialResult]] = {}
    try:
        total = len(PAIRS) * n_trials
        done = 0
        for sc, tg, mag in PAIRS:
            key = pair_key(sc, tg)
            rows = []
            for t_i in range(n_trials):
                done += 1
                log.info(
                    "LIVE %-22s trial %2d/%d (%d/%d overall)", key, t_i + 1, n_trials, done, total
                )
                r = await state.run_attack(sc, tg, mag)
                rows.append(
                    TrialResult(
                        seed=-1,  # LIVE has no seed: the emulator's own clock/physics drive it
                        detected=r.detected,
                        detect_s=r.detection_delay_s,
                        localized_s=r.time_to_localize_s,
                        top1=r.top1,
                        top3=r.top3,
                        ambiguous=r.ambiguous,
                        origin_top3=[],  # not retained by run_attack; top1/top3 booleans suffice
                        rank=1 if r.top1 else (">3" if r.detected and not r.top3 else None),
                        contained=None,  # LIVE is read-only: isolate is never attempted
                        time_to_contain_s=None,
                    )
                )
                log.info("  -> detected=%s top1=%s top3=%s", r.detected, r.top1, r.top3)
            out[key] = rows
    finally:
        await state.attacker.close()
        await state.source.stop()
    return out


# ---------------------------------------------------------------------------------------- summary
def _summarize_pair(key: str, rows: list[TrialResult], mode: str) -> dict[str, object]:
    n = len(rows)
    detected = [r for r in rows if r.detected]
    contained = [r for r in rows if r.contained]
    attempted_contain = [r for r in rows if r.contained is not None]
    return {
        "pair": key,
        "mode": mode,
        "n": n,
        "detected": len(detected),
        "detected_rate": len(detected) / n,
        "top1": sum(r.top1 for r in rows),
        "top1_rate": sum(r.top1 for r in rows) / n,
        "top3": sum(r.top3 for r in rows),
        "top3_rate": sum(r.top3 for r in rows) / n,
        "ambiguous": sum(1 for r in rows if r.ambiguous),
        "mean_detect_s": float(np.mean([r.detect_s for r in detected if r.detect_s is not None]))
        if detected
        else None,
        "mean_localized_s": float(
            np.mean([r.localized_s for r in detected if r.localized_s is not None])
        )
        if detected
        else None,
        "contained": len(contained),
        "contain_attempted": len(attempted_contain),
        "contain_rate_of_attempted": (len(contained) / len(attempted_contain))
        if attempted_contain
        else None,
        "mean_time_to_contain_s": float(
            np.mean([r.time_to_contain_s for r in contained if r.time_to_contain_s is not None])
        )
        if contained
        else None,
    }


def _pick_primary_backup(
    summaries: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    """Primary = highest top1_rate, ties broken by detected_rate; backup = runner-up."""
    ranked = sorted(summaries, key=lambda s: (s["top1_rate"], s["detected_rate"]), reverse=True)
    return ranked[0], ranked[1]


def build_report(
    sim: dict[str, list[TrialResult]] | None, live: dict[str, list[TrialResult]] | None
) -> dict[str, object]:
    report: dict[str, object] = {}
    for mode, data in (("sim", sim), ("live", live)):
        if data is None:
            continue
        summaries = [_summarize_pair(k, rows, mode) for k, rows in data.items()]
        primary, backup = _pick_primary_backup(summaries)
        report[mode] = {
            "pairs": {
                k: {**_summarize_pair(k, rows, mode), "trials": [vars(r) for r in rows]}
                for k, rows in data.items()
            },
            "primary": {
                "pair": primary["pair"],
                "n": primary["n"],
                "top1_rate": primary["top1_rate"],
                "detected_rate": primary["detected_rate"],
                "reason": f"highest measured Top-1 rate ({primary['top1_rate']:.0%}) over "
                f"{primary['n']} fresh trials",
            },
            "backup": {
                "pair": backup["pair"],
                "n": backup["n"],
                "top1_rate": backup["top1_rate"],
                "detected_rate": backup["detected_rate"],
                "reason": f"second-highest measured Top-1 rate ({backup['top1_rate']:.0%}) over "
                f"{backup['n']} fresh trials",
            },
        }
    return report


def write_markdown(report: dict[str, object], path: Path) -> None:
    lines = ["# Demo trials (Phase 14 C1)", ""]
    for mode in ("sim", "live"):
        if mode not in report:
            continue
        m = report[mode]
        assert isinstance(m, dict)
        primary, backup = m["primary"], m["backup"]
        lines += [
            f"## {mode.upper()}",
            "",
            f"Primary: **{primary['pair']}** -- {primary['reason']}",
        ]
        lines += [f"Backup: **{backup['pair']}** -- {backup['reason']}", ""]
        lines.append(
            "| Pair | n | Detected | Top-1 | Top-3 | Ambiguous | Mean localize (s) | "
            + ("Contained (of attempted) |" if mode == "sim" else "|")
        )
        lines.append("|---|---|---|---|---|---|---|" + ("---|" if mode == "sim" else ""))
        for key, p in m["pairs"].items():
            row = (
                f"| {key} | {p['n']} | {p['detected']}/{p['n']} | {p['top1_rate']:.0%} | "
                f"{p['top3_rate']:.0%} | {p['ambiguous']} | "
                f"{p['mean_localized_s']:.1f}"
                if p["mean_localized_s"] is not None
                else "n/a"
            )
            if mode == "sim":
                c = (
                    f"{p['contained']}/{p['contain_attempted']}"
                    if p["contain_attempted"]
                    else "n/a"
                )
                row = f"{row} | {c} |"
            else:
                row = f"{row} |"
            lines.append(row)
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sim-only", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument(
        "--n", type=int, default=N_TRIALS, help="trials per pair (smoke-test with a small n)"
    )
    ap.add_argument("--out", default=None, help="override the output basename (for a smoke test)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = get_settings()

    sim_rows = None if args.live_only else run_sim(settings, args.n)
    live_rows = None if args.sim_only else asyncio.run(run_live(settings, args.n))

    report = build_report(sim_rows, live_rows)
    base = args.out or "demo_trials"
    out = settings.reports_dir / f"{base}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=vars))
    write_markdown(report, settings.reports_dir / f"{base}.md")
    for mode in ("sim", "live"):
        if mode in report:
            m = report[mode]
            assert isinstance(m, dict)
            p = m["primary"]
            log.info(
                "%s primary: %s (top1=%.0f%%, n=%d)", mode, p["pair"], p["top1_rate"] * 100, p["n"]
            )
    log.info("wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
