"""Phase 3.1: adversarial re-review of the Phase 3 evidence ledger. Each test here reproduces a
concrete defect found by independently re-reading `app/evidence.py`, `app/engine.py`,
`app/engine_hai.py`, `app/live/runtime.py`, `app/main.py` and `app/api/rest.py` rather than
trusting the Phase 3 report, and then proves the fix. The final section empirically demonstrates
the one limitation the Phase 3 threat model already claimed in prose: a full, internally-consistent
database rewrite is NOT detected by `verify()` -- only tampering that breaks the existing chain is.
"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.evidence import IncidentStore, _record_hash, canonical_payload
from app.main import create_app
from app.schemas import Incident


def _sample_incident(id_: str = "inc_001", status: str = "open") -> Incident:
    return Incident(
        id=id_,
        status=status,  # type: ignore[arg-type]
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
        mode="live",
        ambiguous=False,
    )


# --------------------------------------------------------------------- 1. production-start crash
def test_a_corrupted_incidents_db_degrades_gracefully_instead_of_crashing_the_whole_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the fix: `IncidentStore(settings.live_db)` in `create_app`'s lifespan was unguarded,
    so a corrupted or unreadable database file raised out of the lifespan context manager and the
    ENTIRE app -- SIM included, which never depended on any database before Phase 3 -- failed to
    start. `build_hai_engine` and `build_live_runtime` both explicitly promise "never raises... a
    bad setting never stops SIM or HAI"; the incidents store now keeps that same promise."""
    corrupted = tmp_path / "corrupted.sqlite"
    corrupted.write_bytes(b"not a sqlite file at all")
    monkeypatch.setenv("AT_LIVE_DB", str(corrupted))
    monkeypatch.setenv("AT_HAI_DIR", str(tmp_path / "no-hai"))
    get_settings.cache_clear()
    try:
        app = create_app()  # true production start: no engine override
        with TestClient(app) as c:
            assert app.state.incidents_store is None  # degraded, not crashed
            assert c.get("/api/status").status_code == 200  # SIM is fully up regardless
    finally:
        get_settings.cache_clear()


def test_an_unwritable_history_db_degrades_gracefully_instead_of_crashing_the_whole_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by actually running `docker compose up` against the Phase 5.1 non-root-user
    Dockerfile change: a pre-existing, root-owned `incidents.sqlite` degraded gracefully (the fix
    above already covers it), but `HistoryStore(settings.history_db)` in the same lifespan had no
    equivalent try/except and crashed the entire backend instead -- this is the companion fix,
    same promise: a bad tag-historian database must not take SIM down with it."""
    # A POSIX permission bit (e.g. mkdir(mode=0o555)) is not reliably unwritable on every CI
    # platform (Windows ignores it outright); a path whose parent component is a plain file is a
    # cross-platform way to make `Path.mkdir(parents=True)` fail for real.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("AT_HISTORY_DB", str(blocker / "history.sqlite"))
    monkeypatch.setenv("AT_HAI_DIR", str(tmp_path / "no-hai"))
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as c:
            assert app.state.history is None  # degraded, not crashed
            assert c.get("/api/status").status_code == 200  # SIM is fully up regardless
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------- 2. restart-recovery consistency
def test_restart_recovery_persists_and_ledgers_the_forced_close(tmp_path: Path) -> None:
    """Before the fix: `IncidentStore.load()` set `inc.status = "closed"` on the in-memory object
    it returned, but never wrote that correction back to the `incidents` table or the ledger. The
    stored row and the ledger's last entry for that incident would disagree with what every
    caller actually saw, forever -- exactly the "state and ledger history must stay consistent"
    property this adversarial review was asked to check."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store.save(_sample_incident(status="open"), event_type="incident_created")

    loaded = store.load("live")
    assert loaded[0].status == "closed"  # the in-memory correction (always worked)

    (row_status,) = store._db.execute(
        "SELECT status FROM incidents WHERE id = 'inc_001'"
    ).fetchone()
    assert row_status == "closed"  # the fix: the current-state row now agrees

    events = store._db.execute(
        "SELECT event_type, payload FROM ledger WHERE entity_id = 'inc_001' ORDER BY seq"
    ).fetchall()
    assert [e[0] for e in events] == ["incident_created", "status_changed"]
    assert '"reason":"restart_recovery"' in events[1][1].replace(" ", "")

    # idempotent: loading again must not re-fire the correction
    store.load("live")
    (count,) = store._db.execute(
        "SELECT COUNT(*) FROM ledger WHERE entity_id = 'inc_001'"
    ).fetchone()
    store.close()
    assert count == 2  # still just the original creation + the one correction


def test_restart_recovery_leaves_an_already_final_incident_untouched(tmp_path: Path) -> None:
    """A genuinely closed/contained incident must not get a spurious restart-recovery event --
    only ones that were truly still running when the process stopped."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store.save(_sample_incident(status="contained"), event_type="incident_created")
    store.load("live")
    (count,) = store._db.execute(
        "SELECT COUNT(*) FROM ledger WHERE entity_id = 'inc_001'"
    ).fetchone()
    store.close()
    assert count == 1  # only the creation event; no fabricated correction


# --------------------------------------------------------------------- 3. concurrent genesis
def test_two_stores_opening_the_same_fresh_file_at_once_do_not_crash(tmp_path: Path) -> None:
    """Before the fix: `_ensure_genesis` only guarded against races between writers sharing ONE
    connection (the in-process lock); two separate `IncidentStore`/connection instances racing to
    open the SAME brand-new file could both pass the `COUNT(*) == 0` check and then have the
    loser's `INSERT` raise `sqlite3.IntegrityError` on the `seq` primary key, uncaught."""
    path = tmp_path / "race.sqlite"
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def open_store() -> None:
        try:
            barrier.wait(timeout=5)
            IncidentStore(path).close()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=open_store) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"opening the same fresh file concurrently raised: {errors}"
    final = IncidentStore(path)
    (count,) = final._db.execute("SELECT COUNT(*) FROM ledger").fetchone()
    result = final.ledger.verify()
    final.close()
    assert count == 1  # exactly one genesis record, not two, not zero
    assert result.status == "verified"


# --------------------------------------------------------- 4. blocked LIVE isolate attempts
def test_a_blocked_live_isolate_attempt_is_still_recorded(engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Before the fix: SIM's `Engine.isolate` recorded both accepted and refused outcomes, but a
    LIVE isolate attempt never reached the engine at all -- `POST /api/isolate` answers 409
    directly in `app/api/rest.py`. An operator genuinely attempting to isolate a node against the
    read-only safety boundary is a security-relevant event too; it was silently dropped."""
    store = IncidentStore(tmp_path / "x.sqlite")
    app = create_app(engine, run_loop=False, incidents_store=store)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.mode = "live"
    with TestClient(app) as c:
        r = c.post(
            "/api/isolate",
            json={"incident_id": "inc_001", "node_id": "P101", "operator": "Alex"},
        )
        assert r.status_code == 409
    rows = store._db.execute(
        "SELECT entity_id, payload FROM ledger WHERE event_type = 'isolation_outcome'"
    ).fetchall()
    store.close()
    assert len(rows) == 1 and rows[0][0] == "inc_001"
    assert '"accepted":false' in rows[0][1].replace(" ", "")
    assert '"reason":"live-read-only"' in rows[0][1].replace(" ", "")


# ----------------------------------------------- 5. what the chain does and does not detect
def test_ordinary_tampering_that_breaks_the_chain_is_detected(tmp_path: Path) -> None:
    """The baseline the next test contrasts against: editing one record WITHOUT recomputing
    anything downstream is caught, as already shown in `test_ledger.py`."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1})
    store.ledger.append("status_changed", "inc_002", {"n": 2})
    store._db.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 1")
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"


def test_a_full_internally_consistent_rewrite_is_not_detected(tmp_path: Path) -> None:
    """The ledger's actual, demonstrated limit: an attacker with write access to the database who
    edits a record AND correctly recomputes every hash and prev_hash from that point forward
    produces a chain that verifies cleanly. This is not a bug -- it is exactly what the Phase 3
    threat model says in prose ("a database attacker who can rewrite every record and recompute
    the complete chain may evade chain-only verification"); this test makes that claim concrete
    and falsifiable instead of merely asserted. A hash chain alone, with no independent anchor
    outside the same database, cannot do better than this."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1, "status": "open"})
    store.ledger.append("status_changed", "inc_002", {"n": 2, "status": "open"})
    store.ledger.append("status_changed", "inc_003", {"n": 3, "status": "open"})

    # The attacker rewrites seq=1's payload, then walks forward recomputing every subsequent
    # record's hash and prev_hash so the chain stays self-consistent end to end.
    rows = store._db.execute(
        "SELECT seq, event_id, ts, event_type, entity_id, payload, prev_hash "
        "FROM ledger ORDER BY seq"
    ).fetchall()
    rewritten = dict.fromkeys(r[0] for r in rows)
    prev_hash = None
    for seq, event_id, ts, event_type, entity_id, payload, old_prev_hash in rows:
        if seq == 1:
            payload = canonical_payload({"n": 1, "status": "FABRICATED-BUT-SELF-CONSISTENT"})
        ph = prev_hash if prev_hash is not None else old_prev_hash
        h = _record_hash(seq, event_id, ts, event_type, entity_id, payload, ph)
        store._db.execute(
            "UPDATE ledger SET payload = ?, prev_hash = ?, hash = ? WHERE seq = ?",
            (payload, ph, h, seq),
        )
        prev_hash = h
        rewritten[seq] = payload
    store._db.commit()

    result = store.ledger.verify()
    stored_payload = store._db.execute("SELECT payload FROM ledger WHERE seq = 1").fetchone()[0]
    store.close()

    assert "FABRICATED-BUT-SELF-CONSISTENT" in stored_payload  # the rewrite really happened
    assert result.status == "verified"  # and chain-only verification does not catch it


# ------------------------------------------------------------ 6. audit history across a restart
def test_the_ledger_itself_stays_verifiable_across_a_restart_with_real_activity(
    engine,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """Phase 4: not just "the incidents table has the right rows after a restart" (already
    covered per-mode in `test_evidence_audit.py`/`test_hai.py`/`test_live_runtime.py`) but "the
    ledger -- the actual evidence -- is still a single, unbroken, independently verifiable chain"
    after a close/reopen cycle with genuine incident and isolate activity in between."""
    from tests.test_isolate import FORCE, opened

    store = IncidentStore(tmp_path / "x.sqlite")
    engine.store = store
    engine._saved = {}
    inc = opened(engine, FORCE)
    engine.isolate(inc.id, "P101", operator="Alex")  # accepted
    engine.isolate(inc.id, "P101", operator="Alex")  # refused: already isolated
    before = store.ledger.verify()
    store.close()

    reopened = IncidentStore(tmp_path / "x.sqlite")
    after = reopened.ledger.verify()
    reopened.close()

    assert before.status == "verified" and before.checked > 1
    assert (
        after.status == "verified" and after.checked == before.checked
    )  # nothing lost, nothing added
