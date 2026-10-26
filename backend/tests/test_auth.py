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
from app.api.security import LoginLockout, RateLimiter
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
    app.state.login_lockout = LoginLockout(settings.auth_lockout_threshold, settings.auth_lockout_s)
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


def test_login_locks_the_account_after_repeated_failures(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, auth_lockout_threshold=3) as c:
        c.app.state.login_limiter = RateLimiter(100)  # type: ignore[attr-defined]
        bad = {"username": "alice", "password": "wrong"}
        for _ in range(3):
            assert c.post("/api/auth/login", json=bad).status_code == 401
        locked = c.post("/api/auth/login", json=bad)
        assert locked.status_code == 429
        assert "account" in locked.json()["detail"]
        assert int(locked.headers["Retry-After"]) >= 1
        # Even the correct password is refused while locked -- the account is locked, not the
        # password attempt.
        good = {"username": "alice", "password": "correct horse"}
        assert c.post("/api/auth/login", json=good).status_code == 429


def test_login_lockout_is_keyed_on_the_account_not_the_client(
    engine: Engine, tmp_path: Path
) -> None:
    with make_client(engine, tmp_path, auth_lockout_threshold=2) as c:
        c.app.state.login_limiter = RateLimiter(100)  # type: ignore[attr-defined]
        bad_alice = {"username": "alice", "password": "wrong"}
        for _ in range(2):
            assert c.post("/api/auth/login", json=bad_alice).status_code == 401
        assert c.post("/api/auth/login", json=bad_alice).status_code == 429
        # casey's account is untouched by alice's lockout.
        good_casey = {"username": "casey", "password": "casey-pw"}
        assert c.post("/api/auth/login", json=good_casey).status_code == 200


def test_login_lockout_clears_on_a_successful_login(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, auth_lockout_threshold=3) as c:
        c.app.state.login_limiter = RateLimiter(100)  # type: ignore[attr-defined]
        bad = {"username": "alice", "password": "wrong"}
        good = {"username": "alice", "password": "correct horse"}
        for _ in range(2):
            assert c.post("/api/auth/login", json=bad).status_code == 401
        assert c.post("/api/auth/login", json=good).status_code == 200
        # The failure count reset on success, so two more wrong attempts don't trip the lock.
        for _ in range(2):
            assert c.post("/api/auth/login", json=bad).status_code == 401
        assert c.post("/api/auth/login", json=good).status_code == 200


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


def test_status_reports_auth_required_when_a_secret_is_configured(client: TestClient) -> None:
    assert client.get("/api/status").json()["auth_required"] is True


def test_status_reports_auth_not_required_without_a_secret(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        assert c.get("/api/status").json()["auth_required"] is False


def test_isolate_falls_back_to_the_client_supplied_name_without_auth(
    engine: Engine, tmp_path: Path
) -> None:
    """Unchanged pre-Phase-1 behavior when AT_AUTH_SECRET is not set, loopback + demo mode."""
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


# ------------------------------------------- Phase 5: fail-closed outside loopback dev, for isolate
@pytest.mark.parametrize(
    ("host", "demo_mode"),
    [("0.0.0.0", True), ("127.0.0.1", False), ("0.0.0.0", False)],
)
def test_isolate_fails_closed_without_auth_outside_loopback_dev(
    engine: Engine, tmp_path: Path, host: str, demo_mode: bool
) -> None:
    """The pre-Phase-1 operator-name fallback must not be reachable in anything resembling a
    production deployment: isolate is the one write action with a real safety-relevant effect,
    and trusting an unauthenticated client-supplied name for it outside loopback-only local demo
    is exactly the gap `require_key` was already hardened against for AT_API_KEY (Phase 14 B3),
    but that hardening never covered AT_AUTH_SECRET. Mirrors
    `test_security.py::test_no_key_fails_closed_outside_loopback_dev`."""
    from .test_security import make_client as make_demo_client

    with make_demo_client(engine, tmp_path, host=host, demo_mode=demo_mode) as c:
        inc = opened(engine, FORCE)
        r = c.post(
            "/api/isolate",
            json={"incident_id": inc.id, "node_id": "P101", "operator": "Alex"},
            headers={"X-API-Key": "test-key-123456"},
        )
        assert r.status_code == 503
        assert "AT_AUTH_SECRET" in r.json()["detail"]
        assert engine.incidents[0].isolated_by is None  # the refusal was not silently applied


def test_isolate_still_falls_back_on_loopback_variants_without_auth(
    engine: Engine, tmp_path: Path
) -> None:
    from .test_security import make_client as make_demo_client

    with make_demo_client(engine, tmp_path, host="localhost") as c:
        inc = opened(engine, FORCE)
        r = c.post(
            "/api/isolate",
            json={"incident_id": inc.id, "node_id": "P101", "operator": "Alex"},
            headers={"X-API-Key": "test-key-123456"},
        )
        assert r.status_code == 200


# --------------------------------------------------------- Phase 5.1: no secrets in logs
def test_no_password_or_token_is_logged_across_a_full_login_cycle(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A successful login, a failed login, and an authenticated isolate call -- across all of it,
    neither the plaintext password nor the issued session token may appear in any log record."""
    import logging

    caplog.set_level(logging.DEBUG)
    ok = client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    assert ok.status_code == 200
    token = ok.json()["token"]

    client.post("/api/auth/login", json={"username": "alice", "password": "a wrong password"})
    client.post(
        "/api/isolate",
        json={"incident_id": "inc_001", "node_id": "P101"},
        headers={"Authorization": f"Bearer {token}"},
    )

    log_text = caplog.text
    assert "correct horse" not in log_text
    assert "a wrong password" not in log_text
    assert token not in log_text


# ----------------------------------------------- Phase 5.3: close the demo-key-only gap
# for /api/attack, /api/reset, /api/mode once real auth is configured (VITE_API_KEY is public:
# compiled into the browser bundle, confirmed in the Phase 5.3 report -- never real authentication).
@pytest.mark.parametrize("path,body", [("/api/reset", None), ("/api/mode", {"mode": "sim"})])
def test_write_endpoints_require_login_when_auth_is_configured(
    client: TestClient, path: str, body: object
) -> None:
    r = client.post(path, json=body)
    assert r.status_code == 401
    assert "Login required" in r.json()["detail"]


def test_attack_requires_login_when_auth_is_configured(client: TestClient) -> None:
    r = client.post(
        "/api/attack", json={"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25}
    )
    assert r.status_code == 401


@pytest.mark.parametrize("path,body", [("/api/reset", None), ("/api/mode", {"mode": "sim"})])
def test_write_endpoints_reject_the_analyst_role(
    client: TestClient, path: str, body: object
) -> None:
    login = client.post("/api/auth/login", json={"username": "casey", "password": "casey-pw"})
    token = login.json()["token"]
    r = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.parametrize("path,body", [("/api/reset", None), ("/api/mode", {"mode": "sim"})])
def test_write_endpoints_accept_the_operator_role(
    client: TestClient, path: str, body: object
) -> None:
    login = client.post("/api/auth/login", json={"username": "alice", "password": "correct horse"})
    token = login.json()["token"]
    r = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_write_endpoints_unchanged_without_auth_configured(engine: Engine, tmp_path: Path) -> None:
    """Unmodified pre-Phase-5.3 behavior when AT_AUTH_SECRET is not set: the demo API key (or,
    for loopback + demo mode, no key at all) is still the only control -- no login is required."""
    from .test_security import make_client as make_demo_client

    with make_demo_client(engine, tmp_path) as c:
        assert c.post("/api/reset", headers={"X-API-Key": "test-key-123456"}).status_code == 200


# require_read_access_when_configured: incident-detail READ endpoints, once AT_AUTH_SECRET is
# configured, require login too -- previously open to any network-reachable client regardless of
# auth configuration (a vulnerability-review finding: the write-side gate above was never applied
# to the read side, which carries the same forensic detail).
READ_ENDPOINTS = ["/api/incidents", "/api/metrics", "/api/history?node=LIT101", "/api/live/health"]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoints_require_login_when_auth_is_configured(
    client: TestClient, path: str
) -> None:
    r = client.get(path)
    assert r.status_code == 401
    assert "Login required" in r.json()["detail"]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoints_accept_either_role_once_logged_in(client: TestClient, path: str) -> None:
    """Unlike writes, reads don't need the operator role specifically -- an analyst may read
    incident detail, just not act on it."""
    login = client.post("/api/auth/login", json={"username": "casey", "password": "casey-pw"})
    token = login.json()["token"]
    r = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code != 401


def test_status_and_topology_stay_open_without_login_even_with_auth_configured(
    client: TestClient,
) -> None:
    """/api/status and /api/topology are deliberately NOT gated: the frontend calls /api/status
    before any login exists, to learn whether auth_required is true in the first place -- gating
    it would make the login flow unable to bootstrap. Neither carries incident detail."""
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/topology").status_code == 200


def test_read_endpoints_unchanged_without_auth_configured(engine: Engine, tmp_path: Path) -> None:
    from .test_security import make_client as make_demo_client

    with make_demo_client(engine, tmp_path) as c:
        assert c.get("/api/incidents").status_code == 200
