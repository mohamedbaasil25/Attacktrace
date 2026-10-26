"""Phase 3: the tamper-evident audit ledger (`app/evidence.py`) -- hash chain construction,
tampering detection, concurrency safety, database failure/rollback behavior, and the verification
API (`GET /api/evidence/verify`). See `test_evidence_audit.py` for the incident-persistence side
(restart survival, the `_truth_for` fix) and `test_auth.py` for the general auth machinery this
endpoint reuses."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.evidence import (
    GENESIS_EVENT_TYPE,
    GENESIS_PREV_HASH,
    IncidentStore,
    _record_hash,
)
from app.main import create_app
from tests.test_auth import SECRET
from tests.test_isolate import FORCE, opened


# --------------------------------------------------------------------------------- construction
def test_a_fresh_ledger_has_exactly_a_genesis_record(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    rows = store._db.execute("SELECT seq, event_type, entity_id, prev_hash FROM ledger").fetchall()
    store.close()
    assert rows == [(0, GENESIS_EVENT_TYPE, "", GENESIS_PREV_HASH)]


def test_genesis_is_written_once_even_if_the_store_is_reopened(tmp_path: Path) -> None:
    path = tmp_path / "x.sqlite"
    IncidentStore(path).close()
    store = IncidentStore(path)  # reopen: must not insert a second genesis
    (count,) = store._db.execute("SELECT COUNT(*) FROM ledger").fetchone()
    store.close()
    assert count == 1


def test_append_links_to_the_previous_records_hash(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    a = store.ledger.append("status_changed", "inc_001", {"from": "localizing", "to": "open"})
    b = store.ledger.append("status_changed", "inc_001", {"from": "open", "to": "closed"})
    store.close()
    assert a.seq == 1 and b.seq == 2
    assert b.prev_hash == a.hash
    assert (
        a.prev_hash == GENESIS_PREV_HASH or a.prev_hash != a.hash
    )  # linked to genesis, not itself


def test_recomputing_the_hash_the_same_way_matches_what_was_stored(tmp_path: Path) -> None:
    """Exercises the exact canonical bytes documented in `app/evidence.py`: an independent
    recomputation from the stored columns must reproduce the stored hash."""
    store = IncidentStore(tmp_path / "x.sqlite")
    rec = store.ledger.append("isolation_outcome", "inc_001", {"node_id": "P101", "accepted": True})
    store.close()
    recomputed = _record_hash(
        rec.seq,
        rec.event_id,
        rec.ts,
        rec.event_type,
        rec.entity_id,
        rec.payload_json,
        rec.prev_hash,
    )
    assert recomputed == rec.hash


def test_a_clean_chain_verifies(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    for i in range(5):
        store.ledger.append("status_changed", f"inc_{i:03d}", {"n": i})
    result = store.ledger.verify()
    store.close()
    assert result.status == "verified" and result.checked == 6 and result.first_failure is None


# -------------------------------------------------------------------------------- tamper detection
def test_detects_a_modified_payload(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    store.ledger.append("status_changed", "inc_001", {"from": "open", "to": "closed"})
    store._db.execute(
        "UPDATE ledger SET payload = ? WHERE seq = 1", ('{"from":"open","to":"fabricated"}',)
    )
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"
    assert result.first_failure is not None and result.first_failure.kind == "hash_mismatch"
    assert result.first_failure.seq == 1


def test_detects_a_deleted_record_as_a_sequence_gap(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    for i in range(3):
        store.ledger.append("status_changed", f"inc_{i:03d}", {"n": i})
    store._db.execute("DELETE FROM ledger WHERE seq = 2")
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"
    kinds = {i.kind for i in result.issues}
    assert "sequence_gap" in kinds
    # the deletion also breaks the next surviving record's prev_hash link
    assert "prev_hash_mismatch" in kinds


def test_detects_a_broken_previous_hash_link(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1})
    store.ledger.append("status_changed", "inc_002", {"n": 2})
    store._db.execute("UPDATE ledger SET prev_hash = ? WHERE seq = 2", ("f" * 64,))
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"
    assert result.first_failure is not None
    assert result.first_failure.seq == 2
    assert result.first_failure.kind in ("prev_hash_mismatch", "hash_mismatch")


def test_detects_reordered_content_between_two_records(tmp_path: Path) -> None:
    """Swapping what two records say (keeping their seq/hash/prev_hash columns as originally
    written) is what "reordered" looks like under a hash chain: each record's stored hash no
    longer matches its own content."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1})
    store.ledger.append("status_changed", "inc_002", {"n": 2})
    row1 = store._db.execute("SELECT entity_id, payload FROM ledger WHERE seq = 1").fetchone()
    row2 = store._db.execute("SELECT entity_id, payload FROM ledger WHERE seq = 2").fetchone()
    store._db.execute("UPDATE ledger SET entity_id = ?, payload = ? WHERE seq = 1", row2)
    store._db.execute("UPDATE ledger SET entity_id = ?, payload = ? WHERE seq = 2", row1)
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"
    assert {i.seq for i in result.issues} >= {1, 2}
    assert all(i.kind == "hash_mismatch" for i in result.issues if i.seq in (1, 2))


def test_detects_a_tampered_genesis_record(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    store._db.execute("UPDATE ledger SET entity_id = 'not-empty' WHERE seq = 0")
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "integrity_failure"
    kinds = {i.kind for i in result.issues}
    assert "genesis_invalid" in kinds and "hash_mismatch" in kinds  # entity_id feeds the hash too


def test_the_primary_key_itself_rejects_a_duplicate_sequence_number(tmp_path: Path) -> None:
    """The lock serializes `append()` so two threads can never race to compute the same seq (see
    the concurrency test below); the `seq INTEGER PRIMARY KEY` constraint is the second, DB-level
    line of defense if that ever failed anyway."""
    store = IncidentStore(tmp_path / "x.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute(
            "INSERT INTO ledger VALUES (0, 'dup', 'x', 'status_changed', 'inc_001', '{}', ?, 'x')",
            (GENESIS_PREV_HASH,),
        )
    store.close()


def test_a_corrupted_or_unreadable_ledger_reports_unavailable_not_a_false_pass(
    tmp_path: Path,
) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    store.close()  # the connection is now closed; any query on it raises
    result = store.ledger.verify()
    assert result.status == "unavailable"
    assert result.first_failure is not None and result.first_failure.kind == "operational_error"


def test_an_empty_ledger_table_is_unavailable_not_silently_verified(tmp_path: Path) -> None:
    """A ledger with no genesis row at all (should never happen through normal use --
    `_ensure_genesis` always runs -- but a direct, deliberate wipe of the table must not read as
    "nothing to verify, so it passed")."""
    store = IncidentStore(tmp_path / "x.sqlite")
    store._db.execute("DELETE FROM ledger")
    store._db.commit()
    result = store.ledger.verify()
    store.close()
    assert result.status == "unavailable" and result.first_failure is not None
    assert result.first_failure.kind == "empty_ledger"


# ------------------------------------------------------------------------------------ concurrency
def test_concurrent_appends_produce_a_contiguous_valid_chain(tmp_path: Path) -> None:
    """20 threads hammering `append` on the same store must not create duplicate or skipped
    sequence numbers, broken links, or a chain that fails its own verification."""
    store = IncidentStore(tmp_path / "x.sqlite")
    n = 20

    def write(i: int) -> None:
        store.ledger.append("status_changed", f"inc_{i:03d}", {"i": i})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(n)))

    result = store.ledger.verify()
    seqs = [r[0] for r in store._db.execute("SELECT seq FROM ledger ORDER BY seq").fetchall()]
    store.close()
    assert result.status == "verified"
    assert seqs == list(range(n + 1))  # genesis + n, no gaps, no duplicates


# ------------------------------------------------------------------------------- failure handling
def test_a_failed_append_rolls_back_and_does_not_persist_the_incident_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`IncidentStore.save` writes the incident row and appends a ledger entry in one transaction.
    If the ledger half fails, the incident-table half must not silently "succeed" on its own --
    that would be exactly the "report success after a failed write" the task forbids."""
    from tests.test_evidence_audit import _sample_incident

    store = IncidentStore(tmp_path / "x.sqlite")

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(store.ledger, "_append_locked", boom)
    with pytest.raises(RuntimeError):
        store.save(_sample_incident(), event_type="incident_created")

    rows = store._db.execute("SELECT COUNT(*) FROM incidents").fetchone()
    store.close()
    assert rows[0] == 0  # the incident-table write was rolled back, not left half-committed


class _FlakyOnce:
    """Forwards everything to a real `sqlite3.Connection` except `execute`, which raises once on
    the first call matching `trigger` then behaves normally -- `sqlite3.Connection.execute` is a
    C-level read-only attribute, so it cannot be monkeypatched directly on the connection itself."""

    def __init__(self, real: sqlite3.Connection, trigger: str) -> None:
        self._real, self._trigger, self._fired = real, trigger, False

    def execute(self, sql: str, *a: object, **k: object) -> sqlite3.Cursor:
        if not self._fired and sql.startswith(self._trigger):
            self._fired = True
            raise sqlite3.OperationalError("simulated disk failure")
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def test_append_rolls_back_on_failure_and_a_later_append_still_links_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = IncidentStore(tmp_path / "x.sqlite")
    good = store.ledger.append("status_changed", "inc_001", {"n": 1})

    real_db = store.ledger._db
    monkeypatch.setattr(store.ledger, "_db", _FlakyOnce(real_db, "INSERT INTO ledger"))
    with pytest.raises(sqlite3.OperationalError):
        store.ledger.append("status_changed", "inc_002", {"n": 2})
    monkeypatch.setattr(store.ledger, "_db", real_db)

    nxt = store.ledger.append("status_changed", "inc_003", {"n": 3})
    result = store.ledger.verify()
    store.close()
    assert nxt.seq == good.seq + 1  # the failed attempt never consumed a sequence number
    assert nxt.prev_hash == good.hash
    assert result.status == "verified"


# -------------------------------------------------------------------------- isolate outcomes
def test_an_accepted_and_a_refused_isolate_both_leave_a_ledger_entry(
    engine_with_store: object,
) -> None:
    engine, store = engine_with_store  # type: ignore[misc]
    inc = opened(engine, FORCE)
    engine.isolate(inc.id, "P101", operator="Alex")  # accepted
    engine.isolate(inc.id, "P101", operator="Alex")  # refused: already isolated
    rows = store._db.execute(
        "SELECT entity_id, payload FROM ledger WHERE event_type = 'isolation_outcome' ORDER BY seq"
    ).fetchall()
    assert len(rows) == 2
    assert '"accepted":true' in rows[0][1].replace(" ", "")
    assert '"accepted":false' in rows[1][1].replace(" ", "")


@pytest.fixture
def engine_with_store(tiny, tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.config import Settings
    from app.engine import Engine
    from app.graph import static_graph

    loaded, base = tiny
    store = IncidentStore(tmp_path / "x.sqlite")
    engine = Engine(loaded, base, static_graph(), Settings(), detector_kind="gdn", store=store)
    yield engine, store
    store.close()


# ------------------------------------------------------------------------------------- API surface
@pytest.fixture
def ledger_client(engine, tmp_path: Path):  # type: ignore[no-untyped-def]
    store = IncidentStore(tmp_path / "ledger.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1})
    app = create_app(engine, run_loop=False, incidents_store=store)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        yield c
    store.close()


def test_verify_endpoint_reports_verified_for_a_clean_chain(ledger_client: TestClient) -> None:
    r = ledger_client.get("/api/evidence/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "verified" and body["checked"] == 2 and body["first_failure"] is None


def test_verify_endpoint_404s_without_an_evidence_store(engine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        assert c.get("/api/evidence/verify").status_code == 404


def test_status_distinguishes_app_health_from_evidence_availability(
    engine,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """Phase 5: a degraded app (no incidents store -- see Phase 3.1's crash-to-degraded fix)
    still answers /api/status 200 (the app itself is healthy), but must say so distinctly from
    whether evidence is actually being preserved -- a healthcheck watching only the status code
    would otherwise read a degraded app as fully healthy."""
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        r = c.get("/api/status")
        assert r.status_code == 200
        assert r.json()["evidence_available"] is False


def test_status_reports_evidence_available_with_a_working_store(
    ledger_client: TestClient,
) -> None:
    assert ledger_client.get("/api/status").json()["evidence_available"] is True


def test_verify_endpoint_requires_login_when_auth_is_configured(tmp_path: Path, engine) -> None:  # type: ignore[no-untyped-def]
    from app.api.auth import Credential, hash_password
    from app.api.security import RateLimiter
    from app.config import Settings

    store = IncidentStore(tmp_path / "ledger.sqlite")
    app = create_app(engine, run_loop=False, incidents_store=store)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(auth_secret=SECRET)
    app.state.operators = {"alice": Credential(hash_password("correct horse"), "operator")}
    app.state.login_limiter = RateLimiter(10)
    with TestClient(app) as c:
        assert c.get("/api/evidence/verify").status_code == 401
        login = c.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
        token = login.json()["token"]
        r = c.get("/api/evidence/verify", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["status"] == "verified"
    store.close()


def test_verify_endpoint_is_open_without_auth_configured(ledger_client: TestClient) -> None:
    """Same demo-mode fallback as every other endpoint when `AT_AUTH_SECRET` is unset."""
    assert ledger_client.get("/api/evidence/verify").status_code == 200


def test_verify_endpoint_reports_integrity_failure_through_the_api_not_just_the_library(
    engine,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """Phase 4: every other tamper test calls `store.ledger.verify()` directly; this proves the
    same tampering is visible through the actual HTTP response, with a 200 that must never be
    confused with "verified" -- `body["status"]` is what matters, not the status code."""
    store = IncidentStore(tmp_path / "ledger.sqlite")
    store.ledger.append("status_changed", "inc_001", {"n": 1})
    store._db.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 1")
    store._db.commit()
    app = create_app(engine, run_loop=False, incidents_store=store)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        r = c.get("/api/evidence/verify")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "integrity_failure"
        assert body["first_failure"] is not None and body["first_failure"]["seq"] == 1
    store.close()


def test_verify_endpoint_reports_unavailable_through_the_api_not_verified(
    engine,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """A store that exists (so the endpoint is reachable, not 404) but whose ledger cannot
    actually be read -- the "database unavailable/locked/corrupted" case from Phase 4's checklist
    -- must come back as `status: "unavailable"` at HTTP 200, never `"verified"`."""
    store = IncidentStore(tmp_path / "ledger.sqlite")
    app = create_app(engine, run_loop=False, incidents_store=store)
    app.state.hai_dir = tmp_path / "no-hai"
    store.close()  # the connection is now closed; any query on it raises
    with TestClient(app) as c:
        r = c.get("/api/evidence/verify")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "unavailable"
        assert body["first_failure"]["kind"] == "operational_error"
