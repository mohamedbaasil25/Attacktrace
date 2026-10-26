"""Phase 11 B4: API key, demo-mode switch and attack rate limit."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.security import LoginLockout, RateLimiter
from app.config import Settings
from app.engine import Engine
from app.main import create_app

KEY = "test-key-123456"
ATTACK = {"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25}
WRITES = [("/api/attack", ATTACK), ("/api/reset", None), ("/api/mode", {"mode": "sim"})]


def make_client(engine: Engine, tmp_path: Path, **overrides: object) -> TestClient:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    settings = Settings(api_key=KEY, **overrides)  # type: ignore[arg-type]
    app.state.settings = settings
    app.state.attack_limiter = RateLimiter(settings.attack_rate_per_min)
    return TestClient(app)


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(engine, tmp_path) as c:
        yield c


@pytest.mark.parametrize(("path", "body"), WRITES)
def test_write_endpoints_need_the_key(client: TestClient, path: str, body: object) -> None:
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post(path, json=body, headers={"X-API-Key": ""}).status_code == 401
    assert client.post(path, json=body, headers={"X-API-Key": KEY}).status_code == 200


def test_read_endpoints_and_websocket_stay_open(client: TestClient, engine: Engine) -> None:
    engine.step_sample()  # /ws/live sends the latest message on connect
    for path in ("/api/status", "/api/topology", "/api/incidents"):
        assert client.get(path).status_code == 200
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["mode"] == "sim"


def test_wrong_key_does_not_launch_an_attack(client: TestClient, engine: Engine) -> None:
    client.post("/api/attack", json=ATTACK, headers={"X-API-Key": "nope"})
    assert engine._attacks.ground_truth() == []


def test_demo_mode_off_blocks_attacks_only(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, demo_mode=False) as c:
        h = {"X-API-Key": KEY}
        r = c.post("/api/attack", json=ATTACK, headers=h)
        assert r.status_code == 403 and "Demo mode" in r.json()["detail"]
        assert c.post("/api/reset", headers=h).status_code == 200
        assert c.get("/api/status").status_code == 200


def test_attack_endpoint_is_rate_limited(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, attack_rate_per_min=3) as c:
        h = {"X-API-Key": KEY}
        codes = [c.post("/api/attack", json=ATTACK, headers=h).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        blocked = c.post("/api/attack", json=ATTACK, headers=h)
        assert int(blocked.headers["Retry-After"]) >= 1
        assert c.post("/api/reset", headers=h).status_code == 200  # other writes are not limited


def test_rejected_calls_do_not_use_up_the_rate_limit(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, attack_rate_per_min=2) as c:
        for _ in range(5):
            assert c.post("/api/attack", json=ATTACK).status_code == 401  # no key
        assert c.post("/api/attack", json=ATTACK, headers={"X-API-Key": KEY}).status_code == 200


def test_no_key_configured_leaves_writes_open(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings()  # api_key empty, host defaults to loopback, demo_mode on
    with TestClient(app) as c:
        assert c.post("/api/reset").status_code == 200


# -------------------------------------------- Phase 14 B3: fail-closed outside loopback dev
@pytest.mark.parametrize(
    ("host", "demo_mode"),
    [("0.0.0.0", True), ("127.0.0.1", False), ("0.0.0.0", False)],
)
def test_no_key_fails_closed_outside_loopback_dev(
    engine: Engine, tmp_path: Path, host: str, demo_mode: bool
) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(host=host, demo_mode=demo_mode)  # type: ignore[arg-type]
    with TestClient(app) as c:
        r = c.post("/api/reset")
        assert r.status_code == 503
        assert "AT_API_KEY" in r.json()["detail"]


# -------------------------------- Phase 5: the published .env.example placeholder is never real
def test_the_published_placeholder_key_fails_closed_outside_loopback_dev(
    engine: Engine, tmp_path: Path
) -> None:
    """`.env.example` ships `AT_API_KEY=change-me-demo-key` -- a value published in this very
    repo. A deployment that copies the file without changing it must not end up "protected" by a
    publicly known key; it must fail closed exactly as if no key were set at all."""
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(api_key="change-me-demo-key", host="0.0.0.0")  # type: ignore[arg-type]
    with TestClient(app) as c:
        r = c.post("/api/reset")
        assert r.status_code == 503
        assert "placeholder" in r.json()["detail"]
        # and the placeholder itself must never work as a credential, even sent explicitly
        r2 = c.post("/api/reset", headers={"X-API-Key": "change-me-demo-key"})
        assert r2.status_code == 503


def test_the_published_placeholder_key_still_leaves_writes_open_for_loopback_dev(
    engine: Engine, tmp_path: Path
) -> None:
    """Locally (loopback + demo mode), a deployment that never touched the placeholder behaves
    exactly like one that left AT_API_KEY empty -- open for casual local development, same as
    before this fix, not newly broken by it."""
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(api_key="change-me-demo-key")  # type: ignore[arg-type]
    with TestClient(app) as c:
        assert c.post("/api/reset").status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_variants_all_count_as_loopback(engine: Engine, tmp_path: Path, host: str) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(host=host)  # type: ignore[arg-type]
    with TestClient(app) as c:
        assert c.post("/api/reset").status_code == 200


def test_a_configured_key_still_works_regardless_of_host(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, run_loop=False)
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(host="0.0.0.0", api_key=KEY)  # type: ignore[arg-type]
    with TestClient(app) as c:
        assert c.post("/api/reset", headers={"X-API-Key": KEY}).status_code == 200
        assert c.post("/api/reset").status_code == 401  # fails closed to 401, not the 503 path


# -------------------------------------------- Phase 14 B4: rate-limit identity vs X-Forwarded-For
def test_x_forwarded_for_is_ignored_unless_trust_proxy_is_set(
    engine: Engine, tmp_path: Path
) -> None:
    with make_client(engine, tmp_path, attack_rate_per_min=1) as c:
        h = {"X-API-Key": KEY}
        assert c.post("/api/attack", json=ATTACK, headers=h).status_code == 200
        # A different X-Forwarded-For does not grant a fresh quota: the socket peer is used.
        h2 = {"X-API-Key": KEY, "X-Forwarded-For": "9.9.9.9"}
        assert c.post("/api/attack", json=ATTACK, headers=h2).status_code == 429


def test_x_forwarded_for_is_trusted_when_configured(engine: Engine, tmp_path: Path) -> None:
    with make_client(engine, tmp_path, attack_rate_per_min=1, trust_proxy=True) as c:
        h1 = {"X-API-Key": KEY, "X-Forwarded-For": "1.1.1.1"}
        h2 = {"X-API-Key": KEY, "X-Forwarded-For": "2.2.2.2"}
        assert c.post("/api/attack", json=ATTACK, headers=h1).status_code == 200
        assert c.post("/api/attack", json=ATTACK, headers=h2).status_code == 200  # different client
        assert (
            c.post("/api/attack", json=ATTACK, headers=h1).status_code == 429
        )  # same client again


def test_rate_limiter_window_slides() -> None:
    now = [0.0]
    rl = RateLimiter(2, clock=lambda: now[0])
    assert rl.check("a") is None and rl.check("a") is None
    wait = rl.check("a")
    assert wait is not None and 0 < wait <= 60
    assert rl.check("b") is None  # clients are independent
    now[0] = 61.0
    assert rl.check("a") is None


def test_login_lockout_expires_and_is_per_username() -> None:
    now = [0.0]
    lo = LoginLockout(threshold=2, lock_s=30.0, clock=lambda: now[0])
    assert lo.check("alice") is None
    lo.record_failure("alice")
    assert lo.check("alice") is None  # one failure: not locked yet
    lo.record_failure("alice")
    wait = lo.check("alice")
    assert wait is not None and 0 < wait <= 30
    assert lo.check("bob") is None  # a different account is untouched
    now[0] = 30.1
    assert lo.check("alice") is None  # the lock expired
    lo.record_failure("alice")
    assert lo.check("alice") is None  # the failure count also reset on expiry
    lo.record_success("alice")  # clearing a never-locked account is a no-op
    assert lo.check("alice") is None
