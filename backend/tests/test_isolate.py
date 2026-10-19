"""Phase 11 B3: isolate-and-recover. Containment must be earned, never faked."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.attacks import Scenario
from app.config import Settings
from app.engine import Engine
from app.main import create_app
from app.schemas import AttackRequest, Incident

TEST_KEY = "test-key-123456"  # pragma: allowlist secret


def opened(engine: Engine, req: AttackRequest) -> Incident:
    """Run to a quiet start, launch, and step until the incident is `open`."""
    for _ in range(60):
        engine.step_sample()
    engine.launch(req)
    for _ in range(120):
        m = engine.step_sample()
        if m.incident is not None and m.incident.status == "open":
            return m.incident
    raise AssertionError("no open incident")


def step_until(engine: Engine, status: str, n: int) -> Incident | None:
    for _ in range(n):
        m = engine.step_sample()
        if m.incident is not None and m.incident.status == status:
            return m.incident
    return None


FORCE = AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=300)


def test_isolating_the_true_origin_contains_the_incident(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    assert engine.isolate(inc.id, "P101") == (True, None)
    done = step_until(engine, "contained", 160)
    assert done is not None
    assert done.contained_at is not None and done.time_to_contain_s is not None
    assert 0 < done.time_to_contain_s < 80
    assert engine.incidents[0].status == "contained"
    assert all(n.status != "origin" for n in engine.step_sample().nodes)  # rings fade


def test_isolate_attributes_the_operator(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    assert engine.isolate(inc.id, "P101", operator="Alex") == (True, None)
    assert engine.incidents[0].isolated_by == "Alex"
    # survives further localizing-status rebuilds (carried forward via `base.isolated_by`)
    m = engine.step_sample()
    assert m.incident is not None and m.incident.isolated_by == "Alex"


def test_isolate_without_an_operator_leaves_it_unset(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    assert engine.isolate(inc.id, "P101") == (True, None)
    assert engine.incidents[0].isolated_by is None


def test_isolating_a_wrong_node_never_contains(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    assert engine.isolate(inc.id, "PLC2") == (True, None)  # applied, but PLC2 is not attacked
    assert step_until(engine, "contained", 240) is None  # 2 minutes with the attack still acting
    assert engine.incidents[0].status != "contained"
    assert engine.incidents[0].contained_at is None


def test_wrong_then_right_node_still_contains(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    assert engine.isolate(inc.id, "PLC2")[0]
    for _ in range(20):
        engine.step_sample()
    assert engine.isolate(inc.id, "P101")[0]
    assert step_until(engine, "contained", 160) is not None


def test_isolation_after_the_attack_ended_is_not_credited(engine: Engine) -> None:
    short = AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101", duration_s=12)
    for _ in range(60):
        engine.step_sample()
    engine.launch(short)
    inc = None
    for _ in range(120):
        m = engine.step_sample()
        if m.incident and m.incident.status == "open":
            inc = m.incident
            break
    assert inc is not None
    for _ in range(40):  # the 12 s attack is over by now
        engine.step_sample()
    assert engine.isolate(inc.id, "P101")[0]  # nothing live to contain
    assert step_until(engine, "contained", 80) is None


def test_refusals(engine: Engine) -> None:
    assert engine.isolate("inc_001", "P101") == (False, "Incident is not active")  # none yet
    inc = opened(engine, FORCE)
    assert engine.isolate("inc_999", "P101") == (False, "Incident is not active")
    assert engine.isolate(inc.id, "NOPE") == (False, "Unknown node")
    assert engine.isolate(inc.id, "P101")[0]
    assert engine.isolate(inc.id, "P101") == (False, "Node already isolated")
    step_until(engine, "contained", 160)
    assert engine.isolate(inc.id, "PLC1") == (False, "Incident is not active")


def test_reset_clears_isolation(engine: Engine) -> None:
    inc = opened(engine, FORCE)
    engine.isolate(inc.id, "P101")
    engine.reset()
    assert engine._attacks.isolated == set()


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        yield c


def test_isolate_endpoint(client: TestClient, engine: Engine) -> None:
    inc = opened(engine, FORCE)
    r = client.post("/api/isolate", json={"incident_id": inc.id, "node_id": "P101"})
    assert r.status_code == 200 and r.json() == {"accepted": True, "reason": None}
    again = client.post("/api/isolate", json={"incident_id": inc.id, "node_id": "P101"})
    assert again.json() == {"accepted": False, "reason": "Node already isolated"}


def test_isolate_endpoint_attributes_the_operator(client: TestClient, engine: Engine) -> None:
    inc = opened(engine, FORCE)
    r = client.post(
        "/api/isolate", json={"incident_id": inc.id, "node_id": "P101", "operator": "Alex"}
    )
    assert r.status_code == 200 and r.json() == {"accepted": True, "reason": None}
    incidents = client.get("/api/incidents").json()
    assert next(i for i in incidents if i["id"] == inc.id)["isolated_by"] == "Alex"
    assert client.post("/api/isolate", json={"incident_id": "x"}).status_code == 422


def test_isolate_is_409_in_hai_mode_and_needs_the_key(client: TestClient, engine: Engine) -> None:
    client.app.state.mode = "hai"  # type: ignore[attr-defined]
    r = client.post("/api/isolate", json={"incident_id": "inc_001", "node_id": "P101"})
    assert r.status_code == 409 and "HAI" in r.json()["detail"]
    client.app.state.mode = "sim"  # type: ignore[attr-defined]
    client.app.state.settings = Settings(api_key=TEST_KEY)  # type: ignore[attr-defined]
    body = {"incident_id": "inc_001", "node_id": "P101"}
    assert client.post("/api/isolate", json=body).status_code == 401
