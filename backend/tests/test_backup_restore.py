"""Phase 5.1: SQLite-consistent backup/restore for the incidents+ledger store
(`eval/backup_restore.py`). Tests run entirely against isolated `tmp_path` directories -- never
the real `data/` tree -- and measure actual elapsed time rather than asserting an invented one."""

import sqlite3
from pathlib import Path

import pytest

from app.evidence import IncidentStore
from eval.backup_restore import RestoreVerificationError, backup, restore, verify


def _seeded_store(path: Path) -> IncidentStore:
    """A store with real, varied activity: incident creation, a status change, and an isolate
    outcome -- not just a bare genesis record."""
    from app.schemas import Incident

    store = IncidentStore(path)
    inc = Incident(
        id="inc_001",
        status="localizing",
        detected_at=1.0,
        origin=[],
        path=[],
        path_edges=[],
        explanation="x",
        action="x",
        mitre="T0856",
        mitre_name="Spoof Reporting Message",
        baseline_alarms=[],
        ground_truth=None,
        mode="sim",
        ambiguous=False,
    )
    store.save(inc, event_type="incident_created")
    store.save(inc.model_copy(update={"status": "open"}), event_type="status_changed")
    store.ledger.append(
        "isolation_outcome", "inc_001", {"node_id": "P101", "accepted": True, "operator": "Alex"}
    )
    return store


# --------------------------------------------------------------------------------------- backup
def test_backup_produces_an_independently_verifiable_consistent_copy(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path / "live.sqlite")
    report = backup(tmp_path / "live.sqlite", tmp_path / "backup.sqlite")
    store.close()

    assert report["incidents"] == 1
    assert report["ledger_records"] == 4  # genesis + created + status_changed + isolation_outcome
    assert (
        isinstance(report["elapsed_s"], float) and report["elapsed_s"] >= 0.0
    )  # measured, not invented

    verified = verify(tmp_path / "backup.sqlite")
    assert verified["status"] == "verified"
    assert verified["checked"] == 4
    assert verified["incidents"] == 1


def test_backup_is_unaffected_by_concurrent_writes_through_the_same_store(tmp_path: Path) -> None:
    """The online backup API reads a transaction-consistent snapshot regardless of what else is
    happening to the file; this interleaves further writes around the backup call rather than
    quiescing the store first."""
    store = _seeded_store(tmp_path / "live.sqlite")
    store.ledger.append("status_changed", "inc_001", {"from": "open", "to": "closed"})
    report = backup(tmp_path / "live.sqlite", tmp_path / "backup.sqlite")
    store.ledger.append("status_changed", "inc_002", {"from": None, "to": "localizing"})
    store.close()

    verified = verify(tmp_path / "backup.sqlite")
    assert verified["status"] == "verified"
    assert report["ledger_records"] == 5  # includes the first extra append, not the second


# -------------------------------------------------------------------------------------- restore
def test_restore_preserves_incident_records_ledger_sequence_and_counts(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite"
    store = _seeded_store(live)
    before_incidents = store.load()
    before_ledger = store._db.execute(
        "SELECT seq, event_type, entity_id, hash FROM ledger ORDER BY seq"
    ).fetchall()
    store.close()

    backup(live, tmp_path / "backup.sqlite")
    live.unlink()  # simulate the live database being lost/corrupted
    (tmp_path / "live.sqlite-wal").unlink(missing_ok=True)
    (tmp_path / "live.sqlite-shm").unlink(missing_ok=True)

    report = restore(tmp_path / "backup.sqlite", live)
    assert report["status"] == "verified"

    restored = IncidentStore(live)
    after_incidents = restored.load()
    after_ledger = restored._db.execute(
        "SELECT seq, event_type, entity_id, hash FROM ledger ORDER BY seq"
    ).fetchall()
    after_verify = restored.ledger.verify()
    restored.close()

    assert [i.model_dump_json() for i in after_incidents] == [
        i.model_dump_json() for i in before_incidents
    ]
    assert after_ledger == before_ledger  # exact sequence, event types, entity ids, hashes
    assert after_verify.status == "verified" and after_verify.checked == len(before_ledger)


def test_restore_preserves_the_original_until_verification_succeeds(tmp_path: Path) -> None:
    """The live file must never be touched before the candidate is confirmed good, and even on
    success the original is renamed aside, never deleted outright."""
    live = tmp_path / "live.sqlite"
    store = _seeded_store(live)
    store.close()
    backup(live, tmp_path / "backup.sqlite")

    # A second generation of activity after the backup was taken, so pre- and post-restore
    # content genuinely differ -- proving the restore actually replaced something live.
    store2 = IncidentStore(live)
    store2.ledger.append("status_changed", "inc_999", {"from": None, "to": "open"})
    store2.close()

    restore(tmp_path / "backup.sqlite", live)

    preserved = list(tmp_path.glob("live.pre-restore-*.sqlite"))
    assert len(preserved) == 1, "the pre-restore live database must be kept, not deleted"
    old_store = IncidentStore(preserved[0])
    old_rows = old_store._db.execute(
        "SELECT entity_id FROM ledger WHERE entity_id = 'inc_999'"
    ).fetchall()
    old_store.close()
    assert old_rows, "the preserved original still has the activity that happened after the backup"


def test_restore_refuses_a_tampered_backup_and_leaves_the_live_database_untouched(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.sqlite"
    store = _seeded_store(live)
    store.close()
    # The logical content that must survive untouched -- not the raw bytes, which WAL-mode SQLite
    # may legitimately rewrite via its own checkpointing even on an otherwise read-only reopen.
    live_rows_before = (
        sqlite3.connect(live)
        .execute("SELECT seq, event_type, entity_id, hash FROM ledger ORDER BY seq")
        .fetchall()
    )

    backup(live, tmp_path / "backup.sqlite")
    tampered = sqlite3.connect(tmp_path / "backup.sqlite")
    tampered.execute("UPDATE ledger SET payload = '{\"fabricated\":true}' WHERE seq = 1")
    tampered.commit()
    tampered.close()

    with pytest.raises(RestoreVerificationError):
        restore(tmp_path / "backup.sqlite", live)

    live_rows_after = (
        sqlite3.connect(live)
        .execute("SELECT seq, event_type, entity_id, hash FROM ledger ORDER BY seq")
        .fetchall()
    )
    assert live_rows_after == live_rows_before  # logically untouched: same rows, same hashes
    recheck = IncidentStore(live)
    assert recheck.ledger.verify().status == "verified"  # still a clean chain
    recheck.close()
    assert not list(tmp_path.glob("*.restore-staging"))  # no leftover staging file
    assert not list(tmp_path.glob("live.pre-restore-*"))  # nothing was ever moved aside


# ----------------------------------------------------------------------------------------- CLI
def test_cli_verify_exits_nonzero_for_a_tampered_database(tmp_path: Path) -> None:
    import subprocess
    import sys

    live = tmp_path / "live.sqlite"
    store = _seeded_store(live)
    store.close()
    conn = sqlite3.connect(live)
    conn.execute("UPDATE ledger SET payload = '{\"x\":1}' WHERE seq = 1")
    conn.commit()
    conn.close()

    r = subprocess.run(
        [sys.executable, "-m", "eval.backup_restore", "verify", str(live)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "integrity_failure" in r.stdout
