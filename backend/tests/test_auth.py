"""Operator authentication (Production Transition Roadmap, Phase 1): password hashing, token
issue/decode, the /api/auth/login endpoint, and real role enforcement on /api/isolate."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.auth import (
    Credential,
    Operator,
    decode_token,
    hash_password,
    issue_token,
    load_operators,
    verify_password,
)
from app.api.security import RateLimiter
from app.config import Settings
from app.engine import Engine
from app.main import create_app

from .test_isolate import FORCE, opened

SECRET = "test-auth-secret"  # pragma: allowlist secret
ALICE_HASH = hash_password("correct horse")


def make_client(engine: Engine, tmp_path: Path, **overrides: object) -> TestClient:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    settings = Settings(auth_secret=SECRET, **overrides)  # type: ignore[arg-type]
    app.state.settings = settings
    app.state.operators = {
        "alice": Credential(ALICE_HASH, "operator"),
        "casey": Credential(hash_password("casey-pw"), "analyst"),
    }
    app.state.login_limiter = RateLimiter(10)
    return TestClient(app)


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(engine, tmp_path) as c:
        yield c


def test_load_operators_uses_the_configured_roster() -> None:
    roster = [{"username": "bob", "password_hash": ALICE_HASH, "role": "analyst"}]
    settings = Settings(operators=json.dumps(roster))
    ops = load_operators(settings)
    assert set(ops) == {"bob"}
    assert ops["bob"].role == "analyst"


def test_load_operators_falls_back_to_a_demo_operator_in_demo_mode() -> None:
    settings = Settings(demo_mode=True)
    ops = load_operators(settings)
    assert set(ops) == {"demo"}
    assert verify_password("demo", ops["demo"].password_hash)


def test_load_operators_is_empty_outside_demo_mode_with_no_roster() -> None:
    settings = Settings(demo_mode=False)
    assert load_operators(settings) == {}


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hash_rejects_malformed_stored_value() -> None:
    assert not verify_password("hunter2", "not-a-valid-hash")


def test_token_roundtrip() -> None:
    op = Operator("alice", "operator")
    token = issue_token(op, SECRET, ttl_s=60)
    assert decode_token(token, SECRET) == op


def test_token_rejects_a_tampered_signature() -> None:
    token = issue_token(Operator("alice", "operator"), SECRET, ttl_s=60)
    body, _, sig = token.partition(".")
    assert decode_token(f"{body}.{sig[:-1]}x", SECRET) is None


def test_token_rejects_the_wrong_secret() -> None:
    token = issue_token(Operator("alice", "operator"), SECRET, ttl_s=60)
    assert decode_token(token, "a-different-secret") is None  # pragma: allowlist secret


def test_token_expires() -> None:
    clock = [1000.0]
    token = issue_token(Operator("alice", "operator"), SECRET, ttl_s=60, clock=lambda: clock[0])
    assert decode_token(token, SECRET, clock=lambda: clock[0]) is not None
    clock[0] = 1061.0
    assert decode_token(token, SECRET, clock=lambda: clock[0]) is None


def test_login_returns_a_token_for_valid_credentials(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["role"] == "operator"
    assert decode_token(body["token"], SECRET) == Operator("alice", "operator")


def test_login_rejects_the_wrong_password(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_an_unknown_username(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401


def test_login_is_rate_limited(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path) as c:
        c.app.state.login_limiter = RateLimiter(2)  # type: ignore[attr-defined]
        body = {"username": "x", "password": "y"}
        for _ in range(2):
            assert c.post("/api/auth/login", json=body).status_code == 401
        blocked = c.post("/api/auth/login", json=body)
        assert blocked.status_code == 429


def test_login_disabled_when_auth_secret_is_unset(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "demo", "password": "demo"})
        assert r.status_code == 503


def test_isolate_requires_login_when_auth_is_configured(client: TestClient) -> None:
    inc = opened(client.app.state.engine, FORCE)  # type: ignore[attr-defined]
    r = client.post("/api/isolate", json={"incident_id": inc.id, "node_id": "P101"})
    assert r.status_code == 401


def test_isolate_rejects_the_analyst_role(client: TestClient) -> None:
    inc = opened(client.app.state.engine, FORCE)  # type: ignore[attr-defined]
    login = client.post("/api/auth/login", json={"username": "casey", "password": "casey-pw"})
    token = login.json()["token"]
    r = client.post(
        "/api/isolate",
        json={"incident_id": inc.id, "node_id": "P101"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_isolate_accepts_the_operator_role_and_uses_the_verified_identity(
    client: TestClient,
) -> None:
    inc = opened(client.app.state.engine, FORCE)  # type: ignore[attr-defined]
    login = client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    token = login.json()["token"]
    r = client.post(
        "/api/isolate",
        json={"incident_id": inc.id, "node_id": "P101", "operator": "someone-else"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200 and r.json()["accepted"] is True
    # the verified token identity wins, not the client-supplied operator field
    assert client.app.state.engine.incidents[0].isolated_by == "alice"  # type: ignore[attr-defined]


def test_isolate_falls_back_to_the_client_supplied_name_without_auth(
    engine: Engine, tmp_path: Path
) -> None:
    """Unchanged pre-Phase-1 behavior when AT_AUTH_SECRET is not set."""
    from .test_security import make_client as make_demo_client

    with make_demo_client(engine, tmp_path) as c:
        inc = opened(engine, FORCE)
        r = c.post(
            "/api/isolate",
            json={"incident_id": inc.id, "node_id": "P101", "operator": "Alex"},
            headers={"X-API-Key": "test-key-123456"},
        )
        assert r.status_code == 200
        assert engine.incidents[0].isolated_by == "Alex"
