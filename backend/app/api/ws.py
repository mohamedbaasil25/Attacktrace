"""WebSocket `/ws/live`: broadcast-only, reconnect-safe. One message per emit period."""

import asyncio
import contextlib
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import decode_token
from app.runtime import active_runtime

router = APIRouter()
log = logging.getLogger("attacktrace")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def broadcast(self, payload: str) -> None:
        clients = list(self.clients)
        results = await asyncio.gather(
            *(c.send_text(payload) for c in clients), return_exceptions=True
        )
        for c, r in zip(clients, results, strict=True):
            if isinstance(r, Exception):
                self.clients.discard(c)


PRUNE_EVERY_TICKS = 3600  # about 30 min at 2 Hz -- the historian prune does a full table scan


async def run_loop(state: Any, hub: Hub, period_s: float) -> None:
    """Drive the active engine at a fixed real-time cadence without drifting. Only the active
    engine advances, so switching modes pauses the other one where it was. Also feeds the
    tag-level historian and the SOC/SIEM notifier when configured (Production Transition
    Roadmap, Phase 2/3 MVPs) -- neither can affect detection: both are read-only observers of
    the message this tick already produced."""
    next_t = time.monotonic()
    tick = 0
    while True:
        try:
            rt = active_runtime(state)
            msg = rt.step_sample()
            await hub.broadcast(msg.model_dump_json())
            history = getattr(state, "history", None)
            if history is not None:
                history.record(msg)
                tick += 1
                if tick % PRUNE_EVERY_TICKS == 0:
                    history.prune(state.settings.history_retention_hours * 3600.0)
            siem = getattr(state, "siem", None)
            if siem is not None:
                await siem.notify(rt.incidents)
        except Exception:
            log.exception("live tick failed; continuing")
        next_t += period_s
        await asyncio.sleep(max(0.0, next_t - time.monotonic()))


def _origin_allowed(ws: WebSocket) -> bool:
    """Cross-Site WebSocket Hijacking (CSWSH) guard: a browser always sends `Origin` on a
    cross-origin (and same-origin, in most browsers) WS handshake, so a present-but-disallowed
    Origin is rejected. A MISSING Origin is allowed through -- that's how every non-browser client
    connects (the `websockets` Python client used by this project's own eval tooling, `wscat`,
    etc.), and CSWSH is specifically a browser-mediated attack that always sends the header."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    settings = ws.app.state.settings
    return origin in settings.cors_origins


def _ws_operator_ok(ws: WebSocket) -> bool:
    """Mirrors `require_read_access_when_configured`: open when AT_AUTH_SECRET isn't configured,
    otherwise requires a valid operator/analyst token. A browser's native WebSocket API cannot set
    a custom Authorization header on the handshake, so the token travels as a query parameter
    instead (`?token=...`) -- the same short-lived bearer token issued by `/api/auth/login`, never
    a separate long-lived credential."""
    settings = ws.app.state.settings
    if not settings.auth_secret:
        return True
    token = ws.query_params.get("token")
    if not token:
        return False
    return decode_token(token, settings.auth_secret) is not None


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    hub: Hub = ws.app.state.hub
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
    if not _ws_operator_ok(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    try:
        latest = active_runtime(ws.app.state).latest
        if latest is not None:  # a reconnecting client is current immediately
            await ws.send_text(latest.model_dump_json())
        while True:
            await ws.receive_text()  # broadcast-only: inbound frames are ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
        with contextlib.suppress(RuntimeError):
            await ws.close()
