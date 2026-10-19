import json
import time
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.schemas import AttackResponse, Incident, LiveMessage, Status, Topology
from app.sim import NODE_IDS


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"  # never the real download in data/hai
    with TestClient(app) as c:
        yield c


def test_status_and_mode(client: TestClient) -> None:
    s = Status.model_validate(client.get("/api/status").json())
    assert s.mode == "sim" and s.hai_available is False and s.detector_active == "gdn"
    assert s.uptime_s >= 0
    assert client.post("/api/mode", json={"mode": "sim"}).status_code == 200
    assert client.post("/api/mode", json={"mode": "hai"}).status_code == 409
    assert client.post("/api/mode", json={"mode": "xyz"}).status_code == 422


def test_topology(client: TestClient) -> None:
    topo = Topology.model_validate(client.get("/api/topology").json())
    assert [n.id for n in topo.nodes] == list(NODE_IDS)
    assert any(e.src == "LIT101" and e.dst == "PLC1" and e.kind == "static" for e in topo.edges)


def test_attack_validation(client: TestClient) -> None:
    body = {"scenario": "sensor_offset", "target": "LIT101", "magnitude": -20}
    ok = client.post("/api/attack", json=body)
    assert AttackResponse.model_validate(ok.json()).attack_id == "atk_001"
    bad = client.post("/api/attack", json={"scenario": "sensor_offset", "target": "P101"})
    assert bad.status_code == 422 and "cannot target" in bad.json()["detail"]
    unknown = client.post("/api/attack", json={"scenario": "nope", "target": "LIT101"})
    assert unknown.status_code == 422
    zero = {"scenario": "sensor_freeze", "target": "LIT101", "duration_s": 0}
    assert client.post("/api/attack", json=zero).status_code == 422


def test_incidents_and_reset(client: TestClient, engine: Engine) -> None:
    assert client.get("/api/incidents").json() == []
    body = {"scenario": "actuator_force", "target": "P101", "magnitude": 0}
    client.post("/api/attack", json=body)
    for _ in range(240):
        engine.step_sample()
    incidents = [Incident.model_validate(i) for i in client.get("/api/incidents").json()]
    assert incidents and incidents[0].ground_truth is not None
    assert client.post("/api/reset").status_code == 200
    assert client.get("/api/incidents").json() == []


def test_metrics(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/metrics").status_code == 404
    (tmp_path / "metrics.json").write_text(json.dumps({"detection": {"f1": 0.9}}))
    body = client.get("/api/metrics").json()
    assert body["detection"] == {"f1": 0.9}
    # SIM mode (the fixture's default): a live_session block is merged in, no incidents yet.
    session = body["live_session"]
    assert session["mode"] == "sim" and session["false_alarm_per_hour"] == 0.0
    assert session["uptime_s"] >= 0


def test_metrics_merges_live_metrics_without_touching_the_file(
    client: TestClient, tmp_path: Path
) -> None:
    """Phase 13 Part F: reports/live_metrics.json is merged in at response time only."""
    (tmp_path / "metrics.json").write_text(json.dumps({"detection": {"f1": 0.9}}))
    (tmp_path / "live_metrics.json").write_text(json.dumps({"detection": {"f1": 0.5}}))
    body = client.get("/api/metrics").json()
    assert body["detection"] == {"f1": 0.9} and body["live"] == {"detection": {"f1": 0.5}}
    on_disk = json.loads((tmp_path / "metrics.json").read_text())
    assert "live" not in on_disk and "live_session" not in on_disk


def test_metrics_session_false_alarm_rate_counts_incidents_with_no_ground_truth(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    """An incident with no launched attack behind it (ground_truth is None) is a false alarm;
    an incident from a real launched attack is not."""
    (tmp_path / "metrics.json").write_text(json.dumps({"detection": {"f1": 0.9}}))
    body = {"scenario": "actuator_force", "target": "P101", "magnitude": 0}
    client.post("/api/attack", json=body)
    for _ in range(240):
        engine.step_sample()
    incidents = client.get("/api/incidents").json()
    assert incidents and incidents[0]["ground_truth"] is not None
    assert client.get("/api/metrics").json()["live_session"]["false_alarm_per_hour"] == 0.0


def test_metrics_omits_session_in_hai_mode(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    """HAI incidents always carry ground_truth=None by design, so the heuristic doesn't apply.
    `active_runtime` resolves to `state.engine` here (no real HAI runtime configured), so this
    drives the gate the same way a genuine HaiEngine's `.mode == "hai"` would."""
    (tmp_path / "metrics.json").write_text(json.dumps({"detection": {"f1": 0.9}}))
    engine.mode = "hai"  # type: ignore[assignment]
    assert "live_session" not in client.get("/api/metrics").json()


def test_ws_sends_latest_on_connect(client: TestClient, engine: Engine) -> None:
    engine.step_sample()
    with client.websocket_connect("/ws/live") as ws:
        msg = LiveMessage.model_validate_json(ws.receive_text())
    assert msg.mode == "sim" and len(msg.nodes) == len(NODE_IDS)
    keys = set(json.loads(msg.model_dump_json()))
    # Phase 13 added `source_latency_ms` (null outside LIVE); Phase 15+ added `incidents`
    # (additive: `incident` stays as the derived single-incident alias).
    assert keys == {
        "t",
        "mode",
        "nodes",
        "alert",
        "incident",
        "incidents",
        "impact",
        "source_latency_ms",
    }
    assert json.loads(msg.model_dump_json())["source_latency_ms"] is None
    assert all(n.quality is None for n in msg.nodes)  # LIVE-only field


def test_ws_streams_two_messages_per_second(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=True)
    app.state.reports_dir = tmp_path
    with TestClient(app) as c, c.websocket_connect("/ws/live") as ws:
        stamps = []
        for _ in range(5):
            LiveMessage.model_validate_json(ws.receive_text())
            stamps.append(time.monotonic())
    gaps = [b - a for a, b in pairwise(stamps)]
    assert 0.4 < sum(gaps) / len(gaps) < 0.6  # 2 msgs/s


def test_ws_reconnect_is_safe(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=True)
    app.state.reports_dir = tmp_path
    with TestClient(app) as c:
        for _ in range(2):
            with c.websocket_connect("/ws/live") as ws:
                LiveMessage.model_validate_json(ws.receive_text())
        assert len(app.state.hub.clients) <= 1


def test_live_loop_survives_a_failing_tick(engine: Engine, tmp_path: Path) -> None:
    """Regression: an exception inside step_sample used to end the broadcast task silently, so
    the whole UI went quiet. One bad tick must be logged and skipped."""
    real = engine.step_sample
    calls = {"n": 0}

    def flaky() -> LiveMessage:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        return real()

    engine.step_sample = flaky  # type: ignore[method-assign]
    app = create_app(engine, run_loop=True)
    app.state.reports_dir = tmp_path
    with TestClient(app) as c, c.websocket_connect("/ws/live") as ws:
        msg = LiveMessage.model_validate_json(ws.receive_text())
    assert msg.mode == "sim" and calls["n"] >= 3
