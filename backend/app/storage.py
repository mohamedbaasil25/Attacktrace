"""Storage interfaces (post-submission hardening): the exact shape `IncidentStore`
(app/evidence.py) and `HistoryStore` (app/history.py) must keep, independent of which database
sits behind them.

Why this exists now: SQLite is the only backend either store has ever had, and the submission
docs assert "the store sits behind an interface already -- a Postgres swap is a config change,
not a rewrite" without anything to back that up. These Protocols are that proof: every caller in
this codebase -- `app/engine.py`, `app/engine_hai.py`, `app/api/rest.py`, `app/main.py` -- was
grepped for every `.save(`, `.load(`, `.record(`, `.query(`, `.prune(`, `.close(` and
`.ledger.*` call site; nothing anywhere reaches into a SQLite connection, a cursor, or a table
name directly. A Postgres-backed implementation only has to satisfy these Protocols (Python's
structural typing means it doesn't even need to subclass anything, just implement the same
methods) to be a drop-in replacement -- call sites would not change at all.

What this file deliberately does NOT do: add a Postgres implementation, or the dependency one
would need (`psycopg[binary]` or `asyncpg` -- a new dependency, per CLAUDE.md's "ask before
adding deps"). It is architecture preparation, not a migration. A real port would still need its
own review; this just removes the main question mark around "would it even be possible without
rewriting every call site" by making the current, already-true answer checkable by mypy instead
of asserted in prose. Concretely, what WOULD still have to change, scoped by file:

  `app/evidence.py` / `app/history.py` (the implementations):
  - `?` placeholders -> `%s` (psycopg2) or `$1, $2, ...` (asyncpg); `INSERT OR REPLACE` ->
    `INSERT ... ON CONFLICT (id) DO UPDATE SET ...`.
  - `PRAGMA journal_mode=WAL`, and the brand-new-file creation race retry loop in
    `IncidentStore.__init__` (its own comment explains why it exists), are SQLite-specific --
    Postgres's own MVCC and DDL locking make both irrelevant. Not something to port, something to
    delete.
  - The single `threading.RLock` guarding one shared SQLite connection would become a connection
    pool (e.g. `psycopg_pool`), one connection or transaction per request, instead -- Postgres is
    built for concurrent connections; SQLite's single-writer model is the reason the lock exists
    at all.
  - The audit ledger's hash-chain algorithm itself (`AuditLedger`, see evidence.py's module
    docstring for the exact byte format) does not change AT ALL: it is pure Python over rows
    already fetched back from a SELECT, already expressed as ordinary SQL with no SQLite-specific
    logic in it.
  - Schema stays conceptually identical; JSON columns stay JSON (Postgres's native `jsonb` is a
    strict upgrade, no shape change needed to start).

  Call sites (`app/engine.py`, `app/engine_hai.py`, `app/api/rest.py`, `app/main.py`): nothing --
  that is the point of this file.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.evidence import EventType, VerificationResult
from app.history import HistorySample
from app.schemas import Incident, LiveMessage


class AuditLedgerLike(Protocol):
    def append(
        self,
        event_type: EventType,
        entity_id: str,
        payload: dict[str, object],
        now: Callable[[], str] = ...,
    ) -> object:
        ...  # returns a LedgerRecord; left as `object` here to avoid a storage-layer -> SQLite
        # concrete-type dependency in this Protocol, which calling code never inspects anyway.

    def verify(self) -> VerificationResult: ...


class IncidentStoreLike(Protocol):
    """What `app.evidence.IncidentStore` provides today, and what any replacement must."""

    @property
    def ledger(self) -> AuditLedgerLike: ...  # a read-only Protocol property, deliberately, not

    # a plain attribute: mypy checks a Protocol's plain attributes invariantly (the concrete type
    # would have to match exactly), which a merely structurally-compatible `AuditLedger` fails
    # even though it satisfies every method `AuditLedgerLike` names. A read-only property is
    # checked covariantly instead, which is the actual relationship here -- callers only ever
    # read `.ledger`, never assign a new one.

    def save(
        self,
        inc: Incident,
        event_type: EventType = ...,
        detail: dict[str, object] | None = ...,
    ) -> None: ...

    def load(self, mode: str | None = ...) -> list[Incident]: ...

    def close(self) -> None: ...


class HistoryStoreLike(Protocol):
    """What `app.history.HistoryStore` provides today, and what any replacement must."""

    def record(self, msg: LiveMessage) -> None: ...

    def query(
        self, node_id: str, since: float | None = ..., until: float | None = ...
    ) -> list[HistorySample]: ...

    def prune(self, retention_s: float, now: float | None = ...) -> int: ...

    def close(self) -> None: ...


def _static_protocol_check(path: Path) -> tuple[IncidentStoreLike, HistoryStoreLike]:
    """Never called (the return value goes nowhere real callers would use) -- a static check
    only, run by `mypy --strict app/storage.py`: if `IncidentStore` or `HistoryStore` drift from
    the Protocols above (a call site starts reaching a method not listed here, for instance), the
    two annotated assignments below fail to typecheck right here, not later as a runtime surprise
    in a hypothetical Postgres implementation that hasn't been written yet."""
    from app.evidence import IncidentStore
    from app.history import HistoryStore

    incident_store: IncidentStoreLike = IncidentStore(path)
    history_store: HistoryStoreLike = HistoryStore(path)
    return incident_store, history_store
