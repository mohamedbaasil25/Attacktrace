"""Phase 16 B3: per-process (per-container) CPU% and memory over a ~15min LIVE-adjacent run.

Reads `submission/evidence/b3_docker_stats_raw.csv`, produced by a parallel `docker stats
--no-stream` sampling loop (every ~10-13s) run alongside the B2 latency measurement and its
preceding dry-run validation -- both exercised the backend in LIVE mode, so this window reflects
real LIVE-mode load, not an idle stack. Computes mean/max CPU% and a simple linear memory-usage
slope (MiB per minute) per container, to check for the kind of unbounded growth the existing
60-minute soak (`live_soak.json`) was built to catch, and to explain/relate the soak's own 113%
mean-CPU figure to per-container reality.
"""

import csv
import re
from collections import defaultdict
from dataclasses import dataclass

from eval.analysis._util import merge_write_final, reports_dir

CSV_PATH = reports_dir().parent / "submission" / "evidence" / "b3_docker_stats_raw.csv"


@dataclass
class Row:
    t_s: float  # seconds since the first sample for this container
    cpu_pct: float
    mem_mib: float


def _parse_mem_to_mib(s: str) -> float:
    # e.g. "559.1MiB" or "1.2GiB"
    m = re.match(r"([\d.]+)\s*(KiB|MiB|GiB)", s)
    if not m:
        return float("nan")
    val, unit = float(m.group(1)), m.group(2)
    return {"KiB": val / 1024, "MiB": val, "GiB": val * 1024}[unit]


def _parse_timestamp(s: str) -> float:
    # ISO 8601 UTC, "%Y-%m-%dT%H:%M:%S.%fZ"
    from datetime import UTC, datetime

    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return dt.timestamp()


def _load() -> dict[str, list[Row]]:
    by_container: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    with CSV_PATH.open(newline="") as f:
        for rec in csv.DictReader(f):
            try:
                ts = _parse_timestamp(rec["timestamp"])
                cpu = float(rec["cpu_percent"].rstrip("%"))
                mem = _parse_mem_to_mib(rec["mem_usage"].split(" / ")[0])
            except (ValueError, KeyError):
                continue
            by_container[rec["container"]].append((ts, cpu, mem))
    out: dict[str, list[Row]] = {}
    for name, samples in by_container.items():
        samples.sort(key=lambda r: r[0])
        t0 = samples[0][0]
        out[name] = [Row(t - t0, cpu, mem) for t, cpu, mem in samples]
    return out


def _slope_mib_per_min(rows: list[Row]) -> float | None:
    """Least-squares slope of memory (MiB) vs time (minutes). None if fewer than 2 points."""
    if len(rows) < 2:
        return None
    xs = [r.t_s / 60.0 for r in rows]
    ys = [r.mem_mib for r in rows]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den else None


def analyze() -> dict[str, object]:
    by_container = _load()
    per: dict[str, object] = {}
    for name, rows in by_container.items():
        cpu_vals = [r.cpu_pct for r in rows]
        mem_vals = [r.mem_mib for r in rows]
        per[name] = {
            "n_samples": len(rows),
            "window_s": rows[-1].t_s if rows else 0.0,
            "cpu_pct_mean": sum(cpu_vals) / len(cpu_vals) if cpu_vals else None,
            "cpu_pct_max": max(cpu_vals) if cpu_vals else None,
            "mem_mib_first": mem_vals[0] if mem_vals else None,
            "mem_mib_last": mem_vals[-1] if mem_vals else None,
            "mem_mib_slope_per_min": _slope_mib_per_min(rows),
        }
    return {
        "window_description": "docker stats sampled every ~10-13s during the B2 LIVE "
        "end-to-end-latency measurement and its preceding dry-run validation (all LIVE-mode "
        "activity in this session's window), not an idle baseline.",
        "per_container": per,
        "soak_comparison": {
            "soak_mean_cpu_pct_of_one_core": 113,
            "note": "live_soak.json's 113% figure is the BACKEND PROCESS's mean CPU over a full "
            "60-minute soak (not per-container docker stats, which did not exist for that run); "
            "this B3 measurement's backend container cpu_pct_mean is the first directly comparable "
            "per-container figure, over a much shorter and differently-composed window (LIVE-mode "
            "attack bursts + idle periods, not steady 2Hz operation throughout) -- treat as a "
            "sanity cross-check, not a replacement for the soak's own number.",
        },
    }


def main() -> int:
    result = analyze()
    out = merge_write_final("b3_cpu_memory", result)
    per = result["per_container"]
    assert isinstance(per, dict)
    for name, stats in per.items():
        assert isinstance(stats, dict)
        print(
            f"{name}: n={stats['n_samples']} cpu_mean={stats['cpu_pct_mean']:.2f}% "
            f"cpu_max={stats['cpu_pct_max']:.2f}% "
            f"mem_slope={stats['mem_mib_slope_per_min']:.3f} MiB/min "
            f"({stats['mem_mib_first']:.1f}->{stats['mem_mib_last']:.1f} MiB)"
        )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
