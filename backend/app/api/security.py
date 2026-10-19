"""Demo-app protection (Phase 11 B4): API key, attack rate limit, demo-mode switch.

Read-only endpoints and /ws/live stay open. The key is a shared secret for a demo deployment:
the browser build carries it (VITE_API_KEY), so this deters casual misuse of an exposed demo,
it is not user authentication.
"""

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

WINDOW_S = 60.0


class RateLimiter:
    """Sliding window: at most `limit` calls per client within the last minute."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client: str) -> float | None:
        """None when allowed (and counted); else seconds until a slot frees up."""
        now = self._clock()
        hits = self._hits[client]
        while hits and now - hits[0] >= WINDOW_S:
            hits.popleft()
        if len(hits) >= self.limit:
            return WINDOW_S - (now - hits[0])
        hits.append(now)
        return None


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def require_key(request: Request) -> None:
    """401 unless X-API-Key matches AT_API_KEY. With no key configured, write endpoints stay open
    ONLY for loopback-bound local development with demo mode on; anything else -- a non-loopback
    AT_HOST, or AT_DEMO_MODE off -- fails closed (503) instead of silently staying open."""
    settings = request.app.state.settings
    key = settings.api_key
    if not key:
        if _is_loopback(settings.host) and settings.demo_mode:
            return
        raise HTTPException(
            status_code=503,
            detail="AT_API_KEY is not set and this server is not loopback-only local "
            "development (AT_HOST is not loopback, or AT_DEMO_MODE is off): write endpoints "
            "fail closed rather than stay open. Set AT_API_KEY to enable them.",
        )
    sent = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(sent.encode(), key.encode()):
        raise HTTPException(status_code=401, detail="API key required")


def require_demo(request: Request) -> None:
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=403, detail="Demo mode is off")


def limit_attacks(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if request.app.state.settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client = xff.split(",")[0].strip()  # the original client, leftmost per RFC 7239
    wait = request.app.state.attack_limiter.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many attacks, slow down",
            headers={"Retry-After": str(int(wait) + 1)},
        )
