"""Phase 3: durable incident persistence plus a tamper-evident, hash-chained audit ledger.

Replaces `app.live.store.IncidentStore` (moved here, same name, same on-disk `incidents` table
schema) and extends it with an append-only `ledger` table. One shared `IncidentStore` instance,
and therefore one SQLite file, is used by every mode -- SIM, HAI and LIVE alike -- keyed by the
pre-existing `mode` column. This is a deliberate choice not to introduce a second, competing
incident store: the LIVE-only `IncidentStore` already existed and already has the right shape
(current-state table + a `mode` filter on `load()`); Phase 3 generalizes it rather than building a
parallel one for SIM/HAI.

Migration: this reuses the existing `AT_LIVE_DB` setting/file (`Settings.live_db`) unchanged --
no new environment variable, no file move. A `ledger` table is added to that same file alongside
the pre-existing `incidents` table. Incidents written before Phase 3 keep reading back exactly as
before (the `incidents` table schema did not change); they have no corresponding ledger entries,
and none are fabricated retroactively to backfill one -- a chain "proving" the history of events
that happened before the chain existed would itself be fabricated evidence. The chain starts
clean, with a genesis record, from the moment Phase 3 first runs against a given database file.

Evidence model
--------------
The `incidents` table is a legitimate, queryable *current-state* projection -- "what is incident
X right now" should not require replaying the whole ledger -- and is still written with
`INSERT OR REPLACE`. That is fine for a current-state table. What Phase 2's audit actually flagged
was that this was the *only* record: nothing preserved *how* that current state was reached. The
`ledger` table is the actual evidence: append-only, one row per incident creation, status change,
or isolation outcome, each row cryptographically linked to the one before it. `IncidentStore.save`
now writes to both tables in a single SQLite transaction, so a repeated `save()` for the same
incident id still updates the current-state row (expected: that is what "current state" means) but
can never erase the historical record of what happened, because that record lives in the ledger
instead and is never updated or deleted.

Canonical serialization and exact hashed bytes
-----------------------------------------------
A ledger record's payload is serialized with `json.dumps(payload, sort_keys=True,
separators=(",", ":"), ensure_ascii=True)` -- deterministic regardless of dict insertion order,
no incidental whitespace, ASCII-safe across platforms. The hashed material for a record is the
UTF-8 bytes of:

    f"{seq}|{event_id}|{ts}|{event_type}|{entity_id}|{payload_json}|{prev_hash}"

joined with the literal ASCII `|` as a separator. This delimiter is not used to *parse* the string
back apart anywhere: both writing and verifying always reconstruct this exact byte sequence from
the same seven already-separate column values, so the delimiter only has to make the concatenation
deterministic, not unambiguous to re-split -- no value in those seven fields is attacker-influenced
free text with adversarially chosen content except `payload_json`, and that field's own internal
structure is independently canonicalized JSON, not re-parsed from the pipe-joined form.

The genesis record is `seq=0`, `event_id="genesis"`, `event_type="genesis"`, `entity_id=""`,
`payload={}` (serialized as `"{}"`), `prev_hash="0" * 64`, and `hash` computed the same way as
every other record. It is written once, the first time a given database file is opened.

See `verify_chain` for what "tamper-evident" actually checks, and the Phase 3 report's threat
model section for what it deliberately does not protect against.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.schemas import Incident

FINAL = {"closed", "contained"}

GENESIS_PREV_HASH = "0" * 64
GENESIS_EVENT_TYPE = "genesis"
GENESIS_EVENT_ID = "genesis"

EventType = Literal["incident_created", "status_changed", "isolation_outcome"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def canonical_payload(payload: dict[str, object]) -> str:
    """The exact, deterministic JSON text that gets hashed -- sorted keys, no incidental
    whitespace, ASCII-only. Callers must pass this same string back in to recompute a hash; never
    re-serialize a payload a different way and expect the hash to still match."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _record_hash(
    seq: int,
    event_id: str,
    ts: str,
    event_type: str,
    entity_id: str,
    payload_json: str,
    prev_hash: str,
) -> str:
    material = "|".join([str(seq), event_id, ts, event_type, entity_id, payload_json, prev_hash])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerRecord:
    seq: int
    event_id: str
    ts: str
    event_type: str
    entity_id: str
    payload_json: str
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class VerificationIssue:
    """One concrete problem found while walking the chain. `seq` is the record it was found at,
    or `None` for a whole-chain problem (an empty ledger, an unreadable database)."""

    seq: int | None
    kind: str
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    status: Literal["verified", "integrity_failure", "unavailable"]
    checked: int
    first_failure: VerificationIssue | None
    issues: list[VerificationIssue] = field(default_factory=list)


class AuditLedger:
    """The append-only `ledger` table. Shares its connection and lock with the `IncidentStore`
    that owns it, so an incident's current-state write and its ledger entry commit as one SQLite
    transaction -- never one without the other."""

    def __init__(self, db: sqlite3.Connection, lock: threading.RLock) -> None:
        self._db, self._lock = db, lock
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS ledger (
                seq INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                event_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            )"""
        )
        self._db.commit()
        self._ensure_genesis()

    def _ensure_genesis(self) -> None:
        """Idempotent even across two separate `IncidentStore`/connection instances opened on the
        same fresh file at once (concurrent process startup): the in-process `self._lock` only
        serializes writers sharing this one connection, so a second process racing the same file
        can still reach the INSERT after the COUNT(*) check passes for both. Two failure shapes
        can result, and only one of them means "someone else already won the race, fine":
        `IntegrityError` on the `seq` primary key (the other writer's row is already there), or
        `OperationalError` ("database is locked") from SQLite's own busy-handler timing out while
        the two processes contend for the file during its very first initialization. Either way,
        this re-checks that a genesis record genuinely exists afterward before treating the
        failure as benign -- a lock error for some unrelated reason must not be swallowed as if it
        were a resolved race."""
        with self._lock:
            (count,) = self._db.execute("SELECT COUNT(*) FROM ledger").fetchone()
            if count > 0:
                return
            ts = _utc_now_iso()
            payload_json = canonical_payload({})
            h = _record_hash(
                0, GENESIS_EVENT_ID, ts, GENESIS_EVENT_TYPE, "", payload_json, GENESIS_PREV_HASH
            )
            try:
                self._db.execute(
                    "INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        0,
                        GENESIS_EVENT_ID,
                        ts,
                        GENESIS_EVENT_TYPE,
                        "",
                        payload_json,
                        GENESIS_PREV_HASH,
                        h,
                    ),
                )
                self._db.commit()
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                self._db.rollback()
                (count_after,) = self._db.execute("SELECT COUNT(*) FROM ledger").fetchone()
                if count_after == 0:
                    raise  # a genuinely unresolved problem, not a race another writer already won

    def _append_locked(
        self, event_type: str, entity_id: str, payload: dict[str, object], now: Callable[[], str]
    ) -> LedgerRecord:
        """Append within a transaction the caller already holds the lock for; does not commit --
        the caller (either `append` below, or `IncidentStore.save`) decides the transaction
        boundary, so an incident's state and its ledger entry can share one commit."""
        row = self._db.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:  # pragma: no cover -- _ensure_genesis always inserts seq 0 first
            raise RuntimeError("ledger has no genesis record")
        seq, prev_hash = row[0] + 1, row[1]
        event_id = str(uuid.uuid4())
        ts = now()
        payload_json = canonical_payload(payload)
        h = _record_hash(seq, event_id, ts, event_type, entity_id, payload_json, prev_hash)
        self._db.execute(
            "INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, event_id, ts, event_type, entity_id, payload_json, prev_hash, h),
        )
        return LedgerRecord(seq, event_id, ts, event_type, entity_id, payload_json, prev_hash, h)

    def append(
        self,
        event_type: EventType,
        entity_id: str,
        payload: dict[str, object],
        now: Callable[[], str] = _utc_now_iso,
    ) -> LedgerRecord:
        """Standalone append (own transaction) -- for events with no accompanying incident-table
        write. `IncidentStore.save` uses `_append_locked` directly instead, to share one commit."""
        with self._lock:
            try:
                rec = self._append_locked(event_type, entity_id, payload, now)
                self._db.commit()
                return rec
            except Exception:
                self._db.rollback()
                raise

    def verify(self) -> VerificationResult:
        """Walks the whole chain in sequence order and checks: sequence continuity (no gaps, no
        duplicates), event-id uniqueness, genesis shape, previous-hash linkage, and the recomputed
        hash of every record against what is stored. A reordered or deleted record breaks the
        previous-hash link at the point it was removed from; a modified payload or any other field
        breaks the recomputed hash of that record itself. Returns every issue found, not just the
        first, but `first_failure` is what a caller should lead with."""
        try:
            rows = self._db.execute(
                "SELECT seq, event_id, ts, event_type, entity_id, payload, prev_hash, hash "
                "FROM ledger ORDER BY seq ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            return VerificationResult(
                "unavailable", 0, VerificationIssue(None, "operational_error", str(exc)), []
            )
        if not rows:
            issue = VerificationIssue(None, "empty_ledger", "no genesis record found")
            return VerificationResult("unavailable", 0, issue, [issue])

        issues: list[VerificationIssue] = []
        seen_event_ids: set[str] = set()
        expected_seq = 0
        prev_hash = GENESIS_PREV_HASH
        for seq, event_id, ts, event_type, entity_id, payload, ph, h in rows:
            if seq != expected_seq:
                issues.append(
                    VerificationIssue(
                        seq, "sequence_gap", f"expected seq {expected_seq}, found {seq}"
                    )
                )
            if event_id in seen_event_ids:
                issues.append(VerificationIssue(seq, "duplicate_event_id", event_id))
            seen_event_ids.add(event_id)
            if seq == 0 and (
                event_type != GENESIS_EVENT_TYPE or entity_id != "" or ph != GENESIS_PREV_HASH
            ):
                issues.append(
                    VerificationIssue(
                        seq, "genesis_invalid", "genesis record does not match the expected shape"
                    )
                )
            if ph != prev_hash:
                issues.append(
                    VerificationIssue(
                        seq, "prev_hash_mismatch", f"expected prev_hash {prev_hash}, found {ph}"
                    )
                )
            recomputed = _record_hash(seq, event_id, ts, event_type, entity_id, payload, ph)
            if recomputed != h:
                issues.append(
                    VerificationIssue(
                        seq, "hash_mismatch", "stored hash does not match the recomputed one"
                    )
                )
            prev_hash = h
            expected_seq = seq + 1
        status: Literal["verified", "integrity_failure"] = (
            "integrity_failure" if issues else "verified"
        )
        return VerificationResult(status, len(rows), issues[0] if issues else None, issues[:50])


def classify_transition(old: Incident | None, new: Incident) -> tuple[EventType, dict[str, object]]:
    """For a persistence call site that only has "the incident now looks like this" (a diff
    against what was last saved, e.g. `LiveRuntime._persist`), not an explicit reason -- infers
    the most specific event type the diff actually supports. Isolation is reported separately by
    the caller (via `detail`) when it knows one just happened; this only distinguishes creation
    from an ordinary status change."""
    if old is None:
        return "incident_created", {}
    if old.status != new.status:
        return "status_changed", {"from": old.status, "to": new.status}
    if old.isolated_by != new.isolated_by and new.isolated_by is not None:
        return "isolation_outcome", {"operator": new.isolated_by}
    return "status_changed", {"from": old.status, "to": new.status}


def _incident_payload(inc: Incident, detail: dict[str, object] | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "incident_id": inc.id,
        "mode": inc.mode,
        "status": inc.status,
        "detected_at": inc.detected_at,
        "origin_id": inc.origin[0].id if inc.origin else None,
        "origin_confidence": inc.origin[0].confidence if inc.origin else None,
        "ground_truth_attack_id": inc.ground_truth.attack_id if inc.ground_truth else None,
        "isolated_by": inc.isolated_by,
        "contained_at": inc.contained_at,
    }
    if detail:
        payload["detail"] = detail
    return payload


class IncidentStore:
    """SQLite persistence for incidents, now across every mode (Phase 3 generalizes what was
    LIVE-only). Incidents survive a restart; raw tag history does not (only the engine's own
    5-minute in-memory ring buffer exists -- see `app.history.HistoryStore` for that instead)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Two processes racing to initialize the SAME brand-new file -- creating the WAL/journal
        # alongside the tables themselves, not just writing a page -- can hit "database is
        # locked" well inside SQLite's own busy-handler window (reproduced under real thread
        # contention in `tests/test_ledger_adversarial.py`): the busy-timeout retries a single
        # blocked statement, but a lock encountered mid-way through this multi-statement sequence
        # (connect, PRAGMA, two CREATE TABLEs, genesis) can still surface as a raised error rather
        # than a retried one. So the whole sequence retries as a unit, with a fresh connection
        # each attempt, short backoff, a handful of attempts -- past that, something other than
        # ordinary startup contention is wrong, and it should raise for real.
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(5):
            if attempt:
                time.sleep(0.05 * attempt)
            try:
                self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10.0)
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute(
                    """CREATE TABLE IF NOT EXISTS incidents (
                        id TEXT PRIMARY KEY,
                        mode TEXT NOT NULL,
                        detected_at REAL NOT NULL,
                        status TEXT NOT NULL,
                        origin TEXT NOT NULL,   -- ranking with score breakdown (JSON)
                        path TEXT NOT NULL,     -- propagation path (JSON)
                        payload TEXT NOT NULL   -- the full incident (JSON)
                    )"""
                )
                self._db.commit()
                self._lock = threading.RLock()
                self.ledger = AuditLedger(self._db, self._lock)
                return
            except sqlite3.OperationalError as exc:
                last_exc = exc
                with contextlib.suppress(Exception):
                    self._db.close()
        assert last_exc is not None
        raise last_exc

    def save(
        self,
        inc: Incident,
        event_type: EventType = "status_changed",
        detail: dict[str, object] | None = None,
    ) -> None:
        """Updates the current-state row AND appends a ledger entry, as one transaction -- never
        one without the other. `event_type` names what actually happened; the caller knows (it is
        the one driving the incident's lifecycle), so this never has to guess from a diff."""
        with self._lock:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        inc.id,
                        inc.mode,
                        inc.detected_at,
                        inc.status,
                        json.dumps([o.model_dump() for o in inc.origin]),
                        json.dumps([p.model_dump() for p in inc.path]),
                        inc.model_dump_json(),
                    ),
                )
                self.ledger._append_locked(
                    event_type, inc.id, _incident_payload(inc, detail), _utc_now_iso
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def load(self, mode: str | None = None) -> list[Incident]:
        """Stored incidents, oldest first, optionally scoped to one mode. One that was still
        running when the process stopped is reported as closed: nothing was watching it. That
        correction is itself persisted (the current-state row) and ledgered (a `status_changed`
        event, `detail.reason == "restart_recovery"`) -- not just applied to the in-memory object
        returned here. Without that, the stored row and the ledger's last entry for that incident
        would forever disagree with what every caller actually sees and acts on, which is exactly
        the "incident state and ledger history must stay consistent" property an auditor would
        check first. Idempotent: a row already closed this way reads back already-FINAL, so a
        second `load()` call never re-fires the correction."""
        if mode is None:
            rows = self._db.execute(
                "SELECT payload FROM incidents ORDER BY detected_at, id"
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT payload FROM incidents WHERE mode = ? ORDER BY detected_at, id", (mode,)
            ).fetchall()
        out = []
        for (payload,) in rows:
            inc = Incident.model_validate_json(payload)
            if inc.status not in FINAL:
                closed = inc.model_copy(update={"status": "closed"})
                self.save(
                    closed,
                    event_type="status_changed",
                    detail={"from": inc.status, "to": "closed", "reason": "restart_recovery"},
                )
                inc = closed
            out.append(inc)
        return out

    def close(self) -> None:
        self._db.close()
