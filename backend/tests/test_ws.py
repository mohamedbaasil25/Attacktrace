"""/ws/live handshake guards: CSWSH Origin check and the operator-token gate once AT_AUTH_SECRET
is configured (vulnerability-review finding: the WS endpoint previously had neither)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.auth import Credential, Operator, hash_password, issue_token
from app.api.security import RateLimiter
from app.config import Settings
from app.engine import Engine
from app.main import create_app

from .test_auth import SECRET
from .test_security import make_client as make_demo_client


def _make_auth_app(engine: Engine, tmp_path: Path) -> TestClient:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    app.state.settings = Settings(auth_secret=SECRET, cors_origins=["http://allowed.example"])
    app.state.operators = {"alice": Credential(hash_password("correct horse"), "operator")}
    app.state.login_limiter = RateLimiter(10)
    return TestClient(app)


def test_ws_rejects_a_disallowed_origin(engine: Engine, tmp_path: Path) -> None:
    with (
        _make_auth_app(engine, tmp_path) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/live", headers={"origin": "http://evil.example"}),
    ):
        pass
    assert exc.value.code == 4403


def test_ws_allows_a_configured_origin_with_a_valid_token(engine: Engine, tmp_path: Path) -> None:
    token = issue_token(Operator("alice", "operator"), SECRET, 3600.0)
    with (
        _make_auth_app(engine, tmp_path) as client,
        client.websocket_connect(
            f"/ws/live?token={token}", headers={"origin": "http://allowed.example"}
        ) as ws,
    ):
        ws.close()


def test_ws_rejects_missing_token_when_auth_is_configured(engine: Engine, tmp_path: Path) -> None:
    with (
        _make_auth_app(engine, tmp_path) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/live", headers={"origin": "http://allowed.example"}),
    ):
        pass
    assert exc.value.code == 4401


def test_ws_rejects_an_invalid_token_when_auth_is_configured(
    engine: Engine, tmp_path: Path
) -> None:
    with (
        _make_auth_app(engine, tmp_path) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(
            "/ws/live?token=not-a-real-token", headers={"origin": "http://allowed.example"}
        ),
    ):
        pass
    assert exc.value.code == 4401


def test_ws_allows_a_missing_origin_header(engine: Engine, tmp_path: Path) -> None:
    """Non-browser clients (this project's own eval tooling, wscat, curl) don't send Origin at
    all; CSWSH is specifically a browser-mediated attack, so a missing header is let through."""
    token = issue_token(Operator("alice", "operator"), SECRET, 3600.0)
    with (
        _make_auth_app(engine, tmp_path) as client,
        client.websocket_connect(f"/ws/live?token={token}") as ws,
    ):
        ws.close()


def test_ws_unchanged_without_auth_configured(engine: Engine, tmp_path: Path) -> None:
    """Pre-existing behavior: with no AT_AUTH_SECRET, the socket stays open with no token, exactly
    as before the token gate existed. Origin checking still applies (cors_origins defaults apply
    regardless of auth), so connect with no Origin header (the demo client's own default)."""
    with (
        make_demo_client(engine, tmp_path) as client,
        client.websocket_connect("/ws/live") as ws,
    ):
        ws.close()
