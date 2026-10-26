"""Production Readiness Roadmap, Phase 5.1: SQLite-consistent backup and restore for the
incidents+audit-ledger store (`AT_LIVE_DB` / `Settings.live_db`; see `app/evidence.py`).

Why not `cp`: the store runs in WAL mode (`PRAGMA journal_mode=WAL`), so the on-disk `.sqlite`
file can be mid-write relative to its `-wal`/`-shm` siblings at any moment the process is live. A
plain file copy of just the main file risks capturing a torn, inconsistent snapshot. This instead
uses `sqlite3.Connection.backup()` -- SQLite's own online backup API -- which reads through the
engine's transaction-consistent view regardless of what else is happening to the file concurrently,
and needs no downtime and no coordination with the running process.

Restore preserves the original until the restored copy verifies: the candidate is copied to a
staging path and its ledger chain is checked with `AuditLedger.verify()` *before* anything live is
touched. Only on a clean "verified" result is the current live file moved aside (renamed, never
deleted) and the staged copy put in its place. On any failure -- a failed verify, or any exception
-- the live file is left completely untouched and the staging copy is removed.

Usage:
    python -m eval.backup_restore backup  <path/to/live.sqlite> <path/to/backup.sqlite>
    python -m eval.backup_restore restore <path/to/backup.sqlite> <path/to/live.sqlite>
    python -m eval.backup_restore verify  <path/to/either.sqlite>

Measured, not claimed: run `backup`/`restore` and read the printed elapsed time and record counts
for your own database size before relying on any particular duration -- none is hard-coded or
promised here.
"""

import argparse
import logging
import shutil
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("attacktrace.eval.backup_restore")


class RestoreVerificationError(RuntimeError):
    """Raised when a restored copy's ledger does not verify. The live file is never touched when
    this is raised -- see `restore()`."""


def backup(src: Path, dest: Path) -> dict[str, object]:
    """A SQLite-consistent snapshot of `src` written to `dest`, via the online backup API, not a
    file copy. Returns {elapsed_s, incidents, ledger_records} measured on this actual run."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    t0 = time.monotonic()
    src_conn = sqlite3.connect(src)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    elapsed = time.monotonic() - t0

    check = sqlite3.connect(dest)
    try:
        (incidents,) = check.execute("SELECT COUNT(*) FROM incidents").fetchone()
        (ledger_records,) = check.execute("SELECT COUNT(*) FROM ledger").fetchone()
    finally:
        check.close()
    result = {"elapsed_s": elapsed, "incidents": incidents, "ledger_records": ledger_records}
    log.info("backed up %s -> %s: %s", src, dest, result)
    return result


def _verify_file(path: Path) -> dict[str, object]:
    """Opens `path` read-only-in-spirit (via a fresh `IncidentStore`, the same code the running
    app uses) and runs the real `AuditLedger.verify()` -- not a hand-rolled check -- then closes
    it again without leaving the file open."""
    from app.evidence import IncidentStore  # local import: avoids a hard dependency for callers

    store = IncidentStore(path)
    try:
        result = store.ledger.verify()
        (incident_count,) = store._db.execute("SELECT COUNT(*) FROM incidents").fetchone()
    finally:
        store.close()
    return {
        "status": result.status,
        "checked": result.checked,
        "incidents": incident_count,
        "first_failure": None
        if result.first_failure is None
        else {"seq": result.first_failure.seq, "kind": result.first_failure.kind},
    }


def verify(path: Path) -> dict[str, object]:
    return _verify_file(path)


def restore(backup_path: Path, live_path: Path) -> dict[str, object]:
    """Restores `backup_path` over `live_path`. The original at `live_path` is renamed aside
    (never deleted) only after the backup's own ledger verifies clean; on any failure, `live_path`
    is untouched and the staging copy is removed. Raises `RestoreVerificationError` (without
    touching `live_path`) if the backup's chain does not verify."""
    staging = live_path.with_suffix(live_path.suffix + ".restore-staging")
    if staging.exists():
        staging.unlink()
    shutil.copy2(backup_path, staging)

    report = _verify_file(staging)
    if report["status"] != "verified":
        staging.unlink(missing_ok=True)
        raise RestoreVerificationError(
            f"backup at {backup_path} did not verify ({report}); live database left untouched"
        )

    if live_path.exists():
        moved_aside = live_path.with_name(
            f"{live_path.stem}.pre-restore-{int(time.time())}{live_path.suffix}"
        )
        live_path.rename(moved_aside)
        log.info("previous live database preserved at %s, not deleted", moved_aside)
    staging.rename(live_path)
    log.info("restored %s -> %s: %s", backup_path, live_path, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    b = sub.add_parser("backup")
    b.add_argument("src", type=Path)
    b.add_argument("dest", type=Path)
    r = sub.add_parser("restore")
    r.add_argument("backup_path", type=Path)
    r.add_argument("live_path", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("path", type=Path)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.action == "backup":
        print(backup(args.src, args.dest))
    elif args.action == "restore":
        try:
            print(restore(args.backup_path, args.live_path))
        except RestoreVerificationError as exc:
            log.error("%s", exc)
            return 1
    elif args.action == "verify":
        report = verify(args.path)
        print(report)
        return 0 if report["status"] == "verified" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
