"""Demo-app protection (Phase 11 B4): API key, attack rate limit, demo-mode switch.

Read-only endpoints and /ws/live stay open ONLY when AT_AUTH_SECRET is not configured (unchanged
demo behavior). Once it is, incident-detail reads require login too -- see
`require_read_access_when_configured` below, and `app/api/ws.py` for the WebSocket equivalent.
`/api/status` and `/api/topology` always stay open (no incident detail, and the frontend needs
`/api/status` to learn whether login is required in the first place). The key is a shared secret
for a demo deployment: the browser build carries it (VITE_API_KEY), so this deters casual misuse
of an exposed demo, it is not user authentication -- `VITE_*` values are compiled into the public
JavaScript bundle Vite ships to every browser (confirmed empirically in the Phase 5.3 report: the
literal value appears in the built `dist/assets/*.js`), so anyone who opens devtools can read it.
See `require_operator_when_configured` below for the actual authentication gate this implies.
"""

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.api.auth import authenticated_operator

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


class LoginLockout:
    """Per-*username* lockout: locks the account being attacked after `threshold` consecutive
    failed logins, independent of who's asking. Complements `RateLimiter` above (which keys on
    client address and would let an attacker rotating source IPs grind through a weak password
    unbounded) rather than replacing it -- both gates run on every login attempt."""

    def __init__(
        self, threshold: int = 5, lock_s: float = 300.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold = threshold
        self.lock_s = lock_s
        self._clock = clock
        self._failures: dict[str, int] = defaultdict(int)
        self._locked_until: dict[str, float] = {}

    def check(self, username: str) -> float | None:
        """None when login may proceed; else seconds remaining locked. A lock that has expired
        clears itself (and the failure count) here, so the next successful or failed attempt
        starts clean."""
        until = self._locked_until.get(username)
        if until is None:
            return None
        remaining = until - self._clock()
        if remaining <= 0:
            del self._locked_until[username]
            self._failures.pop(username, None)
            return None
        return remaining

    def record_failure(self, username: str) -> None:
        self._failures[username] += 1
        if self._failures[username] >= self.threshold:
            self._locked_until[username] = self._clock() + self.lock_s

    def record_success(self, username: str) -> None:
        self._failures.pop(username, None)
        self._locked_until.pop(username, None)


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


# .env.example ships this literal string as AT_API_KEY's placeholder value, so it is published,
# public, and must never function as a real credential -- a deployment that copies the example
# file verbatim without changing it would otherwise have a well-known, repo-published key
# protecting its write endpoints (Phase 5: "development-only secrets must not silently become
# production credentials"). Treated identically to an unset key below.
PLACEHOLDER_API_KEYS = frozenset({"change-me-demo-key"})


def require_key(request: Request) -> None:
    """401 unless X-API-Key matches AT_API_KEY. With no key configured (or still the
    .env.example placeholder), write endpoints stay open ONLY for loopback-bound local
    development with demo mode on; anything else -- a non-loopback AT_HOST, or AT_DEMO_MODE off
    -- fails closed (503) instead of silently staying open."""
    settings = request.app.state.settings
    key = settings.api_key
    if not key or key in PLACEHOLDER_API_KEYS:
        if _is_loopback(settings.host) and settings.demo_mode:
            return
        raise HTTPException(
            status_code=503,
            detail="AT_API_KEY is not set (or is still the .env.example placeholder value) and "
            "this server is not loopback-only local development (AT_HOST is not loopback, or "
            "AT_DEMO_MODE is off): write endpoints fail closed rather than stay open. Set "
            "AT_API_KEY to a real, non-placeholder value to enable them.",
        )
    sent = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(sent.encode(), key.encode()):
        raise HTTPException(status_code=401, detail="API key required")


def require_operator_when_configured(request: Request) -> None:
    """Phase 5.3: the demo API key (`require_key`, above) is a client-visible deterrent, never
    real authentication -- it is compiled straight into the public browser bundle. `/api/isolate`
    already requires a real, verified operator token whenever `AT_AUTH_SECRET` is configured
    (`app/api/rest.py`); this extends that exact same rule to the other write endpoints
    (`/api/attack`, `/api/reset`, `/api/mode`) so that, once real authentication is configured for
    a deployment, the API key alone can no longer launch or reset the simulator either -- closing
    the gap for every privileged write action, not just isolate.

    Behavior is unchanged when `AT_AUTH_SECRET` is not configured: the demo API key remains the
    only control, exactly as before this function existed. This dependency runs ALONGSIDE
    `require_key` (both still apply), not instead of it."""
    settings = request.app.state.settings
    if not settings.auth_secret:
        return  # auth not configured: unchanged pre-Phase-5.3 behavior (API key only)
    op = authenticated_operator(request)
    if op is None:
        raise HTTPException(
            status_code=401,
            detail="Login required: a real operator session is required once AT_AUTH_SECRET is "
            "configured, because the demo API key alone is visible to every browser user and is "
            "not authentication.",
        )
    if op.role != "operator":
        raise HTTPException(status_code=403, detail="Analyst role cannot perform this action")


def require_read_access_when_configured(request: Request) -> None:
    """Gates incident-detail READ endpoints the same way `require_operator_when_configured` gates
    writes. Unchanged (open) when `AT_AUTH_SECRET` is not configured. Once it is configured, any
    network-reachable client needs a valid operator OR analyst session to read incident detail --
    not just to act on it; a deployment that requires real login to isolate a node but lets anyone
    read every incident's origin, confidence, and explanation text was never actually gated.

    Deliberately NOT applied to `/api/status` or `/api/topology`: the frontend calls `/api/status`
    before any login exists, precisely to learn whether `auth_required` is true in the first place
    -- gating it would make the login flow unable to bootstrap. Neither endpoint carries incident
    detail (status is mode/health only, topology is the static plant graph)."""
    settings = request.app.state.settings
    if not settings.auth_secret:
        return
    if authenticated_operator(request) is None:
        raise HTTPException(
            status_code=401,
            detail="Login required to read incident detail once AT_AUTH_SECRET is configured.",
        )


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


def limit_ai(request: Request) -> None:
    """Ask AI makes a real, billed external API call per question -- rate-limited independently
    of `limit_attacks` so a busy demo session can't also run up a model bill unbounded."""
    client = request.client.host if request.client else "unknown"
    if request.app.state.settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client = xff.split(",")[0].strip()
    wait = request.app.state.ai_limiter.check(client)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many Ask AI requests, slow down",
            headers={"Retry-After": str(int(wait) + 1)},
        )
