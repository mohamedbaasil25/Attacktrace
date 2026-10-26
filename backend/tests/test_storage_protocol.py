"""Postgres-migration prep (app/storage.py): the strongest proof that "a Postgres swap is a
config change, not a rewrite" is an app that actually runs against a store that is NOT
`IncidentStore`/`HistoryStore` -- a fake satisfying only `IncidentStoreLike`/`HistoryStoreLike`,
with no SQLite underneath it at all."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.detect.baseline import BaselineDetector
from app.detect.pipeline import Loaded
from app.engine import Engine
from app.evidence import EventType, VerificationResult
from app.graph import static_graph
from app.history import HistorySample
from app.main import create_app
from app.schemas import Incident, LiveMessage


class FakeLedger:
    def __init__(self) -> None:
        self.appended: list[tuple[EventType, str, dict[str, object]]] = []

    def append(self, event_type: EventType, entity_id: str, payload: dict[str, object]) -> object:
        self.appended.append((event_type, entity_id, payload))
        return None

    def verify(self) -> VerificationResult:
        return VerificationResult(
            status="verified", checked=len(self.appended), first_failure=None, issues=[]
        )


class FakeIncidentStore:
    """No SQLite, no file on disk -- an in-memory dict is the entire "database"."""

    def __init__(self) -> None:
        self.ledger = FakeLedger()
        self._rows: dict[str, Incident] = {}
        self.closed = False

    def save(
        self,
        inc: Incident,
        event_type: EventType = "status_changed",
        detail: dict[str, object] | None = None,
    ) -> None:
        self._rows[inc.id] = inc
        self.ledger.append(event_type, inc.id, detail or {})

    def load(self, mode: str | None = None) -> list[Incident]:
        rows = self._rows.values()
        return [i for i in rows if mode is None or i.mode == mode]

    def close(self) -> None:
        self.closed = True


class FakeHistoryStore:
    def __init__(self) -> None:
        self.recorded: list[LiveMessage] = []
        self.closed = False

    def record(self, msg: LiveMessage) -> None:
        self.recorded.append(msg)

    def query(
        self, node_id: str, since: float | None = None, until: float | None = None
    ) -> list[HistorySample]:
        return []

    def prune(self, retention_s: float, now: float | None = None) -> int:
        return 0

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def client(tiny: tuple[Loaded, BaselineDetector], tmp_path: Path) -> Iterator[TestClient]:
    # Built directly (not via the shared `engine` fixture) so the fake store is wired into the
    # Engine itself, not just handed to `create_app` -- `create_app` only builds its OWN engine
    # (via `build_engine`, which is what actually threads `store=` through) when no `engine=` is
    # injected; a pre-built engine fixture would carry no store at all, and this test is
    # specifically about the store being exercised for real.
    loaded, base = tiny
    fake_store = FakeIncidentStore()
    fake_history = FakeHistoryStore()
    engine = Engine(loaded, base, static_graph(), Settings(), detector_kind="gdn", store=fake_store)
    app = create_app(
        engine,
        run_loop=False,
        incidents_store=fake_store,
        history=fake_history,
    )
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    app.state._fake_store = fake_store  # type: ignore[attr-defined]
    with TestClient(app) as c:
        yield c


def test_app_runs_end_to_end_on_a_non_sqlite_incident_store(client: TestClient) -> None:
    body = {"scenario": "actuator_force", "target": "P101", "magnitude": 0}
    assert client.post("/api/attack", json=body).status_code == 200
    for _ in range(240):
        client.app.state.engine.step_sample()  # type: ignore[attr-defined]
    incidents = client.get("/api/incidents").json()
    assert incidents, "the fake store must actually receive and return incidents"
    fake_store: FakeIncidentStore = client.app.state._fake_store  # type: ignore[attr-defined]
    assert fake_store._rows  # the real engine really did call FakeIncidentStore.save
    assert fake_store.ledger.appended  # and the ledger's append path, not just a bypass


def test_evidence_verify_reads_through_the_fake_ledger(client: TestClient) -> None:
    body = {"scenario": "actuator_force", "target": "P101", "magnitude": 0}
    client.post("/api/attack", json=body)
    for _ in range(240):
        client.app.state.engine.step_sample()  # type: ignore[attr-defined]
    r = client.get("/api/evidence/verify")
    assert r.status_code == 200
    assert r.json()["status"] == "verified"
