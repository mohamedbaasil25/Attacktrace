"""Operator authentication (Production Transition Roadmap, Phase 1): real per-operator identity
and role for the isolate action, replacing the shared demo API key for that one write.

HMAC-signed session tokens and pbkdf2 password hashing -- stdlib only, no new dependency (the
project's dependency list is locked; see `pyproject.toml`). This is not SSO: it's a small,
self-contained operator roster appropriate for a single deployment, not a federated identity
provider. `settings.auth_secret` empty disables it entirely; `post_isolate` then falls back to
trusting the client-supplied operator name, exactly as before this phase.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import Request

from app.config import Settings

Role = Literal["operator", "analyst"]
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    """`salt_hex$hash_hex`. Run once per operator to provision `AT_OPERATORS`; the plaintext
    password is never stored."""
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(candidate.hex(), hash_hex)


@dataclass(frozen=True)
class Operator:
    username: str
    role: Role


@dataclass(frozen=True)
class Credential:
    password_hash: str
    role: Role


def load_operators(settings: Settings) -> dict[str, Credential]:
    """The configured roster, or (demo_mode only) one built-in demo/demo operator so the login
    flow is exercisable out of the box -- same spirit as `require_key`'s unset-api-key path."""
    if settings.operators:
        raw = json.loads(settings.operators)
        return {o["username"]: Credential(o["password_hash"], o["role"]) for o in raw}
    if settings.demo_mode:
        return {"demo": Credential(hash_password("demo"), "operator")}
    return {}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(
    operator: Operator, secret: str, ttl_s: float, clock: Callable[[], float] = time.time
) -> str:
    payload = {"sub": operator.username, "role": operator.role, "exp": clock() + ttl_s}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(
    token: str, secret: str, clock: Callable[[], float] = time.time
) -> Operator | None:
    """None for anything malformed, mis-signed, expired, or with an unrecognized role -- never
    raises, so callers can treat "no operator" uniformly."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < clock():
        return None
    role = payload.get("role")
    sub = payload.get("sub")
    if role not in ("operator", "analyst") or not isinstance(sub, str):
        return None
    return Operator(username=sub, role=role)


def authenticated_operator(request: Request) -> Operator | None:
    """The operator identified by a valid Bearer token, or None -- no/invalid/expired token, or
    auth not configured (`settings.auth_secret` empty). Never raises: read paths can call this
    freely without needing an operator to be present."""
    settings: Settings = request.app.state.settings
    if not settings.auth_secret:
        return None
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    return decode_token(header.removeprefix("Bearer "), settings.auth_secret)
