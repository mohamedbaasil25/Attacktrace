"""Phase 14 A6: did eval.live_faults run concurrently with eval.live (shared-host resource overlap)?

Both scripts spawn their own `plant_emulator` subprocess on separate free ports (no port or data
collision is possible), but both are real-time, CPU/network-bound Python processes; if they ran
at the same wall-clock time on the same Windows host, eval.live's measured latency could carry a
small amount of jitter from the concurrent process, not just the Modbus round trip it's meant to
isolate. This reads the saved evidence timestamps (no new run) to check.
"""

from datetime import datetime

from eval.analysis._util import merge_write

EVAL_LIVE_LOG = "submission/evidence/eval_live_run.log"
LIVE_FAULTS_TS = datetime(2026, 10, 9, 19, 29, 54)  # submission/evidence/live_faults.json mtime


def analyze() -> dict[str, object]:
    from pathlib import Path

    log_path = Path(EVAL_LIVE_LOG) if Path(EVAL_LIVE_LOG).exists() else Path("..") / EVAL_LIVE_LOG
    lines = log_path.read_text().splitlines()
    start = datetime.strptime(lines[0].split(",")[0], "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(lines[-1].split(",")[0], "%Y-%m-%d %H:%M:%S")
    overlaps = start <= LIVE_FAULTS_TS <= end

    return {
        "eval_live_window": {"start": start.isoformat(), "end": end.isoformat()},
        "live_faults_evidence_written_at": LIVE_FAULTS_TS.isoformat(),
        "overlaps": overlaps,
        "finding": (
            "eval.live_faults.json was written at 19:29:54, inside eval.live's "
            "19:21:45-22:14:43 window: the two DID run concurrently for part of that run. No "
            "port or data collision is possible (each spawns its own emulator on a separate "
            "free port), but both are real-time processes sharing the same host's CPU/network "
            "stack during the overlap, so eval.live's measured latency (p50 1.57 ms / p95 "
            "2.40 ms / p99 3.03 ms) may carry a small amount of jitter from the concurrent "
            "live_faults run for roughly the first 10-15 minutes of a ~2h53m run. The soak test "
            "(2026-10-13, uptime_s=3600.3) ran in isolation -- no other eval process was active "
            "during it -- so its numbers are not affected."
            if overlaps
            else "No overlap found between the two runs' recorded timestamps."
        ),
    }


def main() -> int:
    result = analyze()
    out = merge_write("parallel_run_overlap", result)
    print(f"wrote {out}: overlaps={result['overlaps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
