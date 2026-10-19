"""Run every Part A analysis script in sequence, writing reports/fix_analysis.json."""

from eval.analysis import (
    a1_live_miss,
    a2_latency_timing,
    a3_confidence,
    a4_time_to_detect,
    a5_alarm_flood,
    a6_parallel_overlap,
    a7_intervals,
    a8_sustainability,
)


def main() -> int:
    for mod in (
        a1_live_miss,
        a2_latency_timing,
        a3_confidence,
        a4_time_to_detect,
        a5_alarm_flood,
        a6_parallel_overlap,
        a7_intervals,
        a8_sustainability,
    ):
        print(f"--- {mod.__name__} ---")
        mod.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
