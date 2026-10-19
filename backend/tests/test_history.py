"""Tag-level historian (Production Transition Roadmap, Phase 2 MVP): `HistoryStore` and the
`GET /api/history` endpoint."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.history import HistoryStore
from app.main import create_app
from app.schemas import LiveMessage, NodeState


def _msg(t: float, value: float, score: float = 1.0) -> LiveMessage:
    return LiveMessage(
        t=t,
        mode="sim",
        nodes=[NodeState(id="LIT101", value=value, truth=None, score=score, status="normal")],
        alert=None,
        incident=None,
        incidents=[],
        impact=None,
    )


def test_record_and_query_roundtrip(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite")
    store.record(_msg(1.0, 50.0))
    store.record(_msg(2.0, 51.0))
    rows = store.query("LIT101")
    assert [r.value for r in rows] == [50.0, 51.0]
    store.close()


def test_query_filters_by_time_range(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite")
    for t in range(5):
        store.record(_msg(float(t), float(t)))
    rows = store.query("LIT101", since=1.0, until=3.0)
    assert [r.t for r in rows] == [1.0, 2.0, 3.0]
    store.close()


def test_query_is_scoped_to_the_requested_node(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite")
    store.record(
        LiveMessage(
            t=1.0,
            mode="sim",
            nodes=[
                NodeState(id="LIT101", value=1.0, truth=None, score=0.0, status="normal"),
                NodeState(id="LIT301", value=2.0, truth=None, score=0.0, status="normal"),
            ],
            alert=None,
            incident=None,
            incidents=[],
            impact=None,
        )
    )
    assert len(store.query("LIT101")) == 1
    assert len(store.query("LIT301")) == 1
    assert len(store.query("PLC2")) == 0
    store.close()


def test_prune_removes_rows_older_than_retention(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite")
    store.record(_msg(0.0, 1.0))
    store.record(_msg(100.0, 2.0))
    removed = store.prune(retention_s=50.0, now=100.0)
    assert removed == 1
    assert [r.value for r in store.query("LIT101")] == [2.0]
    store.close()


def test_survives_a_sample_with_no_nodes(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite")
    empty = LiveMessage(
        t=0.0, mode="sim", nodes=[], alert=None, incident=None, incidents=[], impact=None
    )
    store.record(empty)  # no rows inserted, no error
    assert store.query("LIT101") == []
    store.close()


@pytest.fixture
def client_with_history(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.history = HistoryStore(tmp_path / "history.sqlite")
    with TestClient(app) as c:
        yield c
    app.state.history.close()


def test_history_endpoint_returns_recorded_samples(client_with_history: TestClient) -> None:
    store: HistoryStore = client_with_history.app.state.history  # type: ignore[attr-defined]
    store.record(_msg(10.0, 42.0))
    r = client_with_history.get("/api/history", params={"node": "LIT101"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["value"] == 42.0


def test_history_endpoint_404s_without_a_historian(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        r = c.get("/api/history", params={"node": "LIT101"})
        assert r.status_code == 404
