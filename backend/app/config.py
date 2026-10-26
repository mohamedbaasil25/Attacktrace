"""Runtime settings from environment variables prefixed `AT_` (see .env.example)."""

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

ENV_PREFIX = "AT_"


class Settings(BaseModel):
    # What this deployment declares itself bound to (Phase 14 B3): loopback-only by default,
    # matching uvicorn's own default when no --host is given. Docker Compose sets AT_HOST=0.0.0.0
    # explicitly, since the container must accept connections from outside itself; this field is
    # the fail-closed signal for `require_key`, separate from the actual uvicorn bind flag.
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]
    seed: int = 42
    sim_hz: float = 10.0
    ws_period_s: float = 0.5
    hai_dir: Path = Path("../data/hai")
    hai_file: str = "test1"  # which HAI test file the replay walks
    hai_speed: float = 10.0  # HAI replay speed, rows per second, clamped to x1..x20
    models_dir: Path = Path("models")
    reports_dir: Path = Path("../reports")
    # Localization weights (score = w1*deviation + w2*onset + w3*causal),
    # tuned on SIM validation attacks in Phase 3.
    w_deviation: float = 0.6
    w_onset: float = 0.2
    w_causal: float = 0.2
    # Confidence gate (Phase 11): an incident is ambiguous when top-1 minus top-2 confidence is
    # below this. Tuned on SIM validation + tuning attacks only (`python -m eval.ambiguity`); the
    # margin is a SIM calibration, so HAI incidents are never flagged.
    gate_margin: float = 0.21
    # Demo protection (Phase 11): empty key = write endpoints open (local dev and tests).
    api_key: str = ""
    demo_mode: bool = True  # False: attack endpoints answer 403
    attack_rate_per_min: int = 10
    # Phase 14 B4: rate-limit identity is the socket peer unless a trusted reverse proxy sets
    # X-Forwarded-For -- an untrusted client could otherwise spoof that header to dodge the limit.
    trust_proxy: bool = False
    # Isolate-and-recover: contained once every node score has stayed under the alert threshold
    # this long after the isolate action. Fixed a priori, not tuned on the test attacks.
    contain_s: float = 5.0
    # Multi-incident admission (Phase 1, SIM/LIVE only): a node whose own persistence counter
    # just crossed PERSIST folds into an already-open incident when it is within this many
    # undirected graph hops of that incident's localized path; otherwise it opens a new one.
    # A heuristic, not a physically-derived constant -- tune against the demo scenarios.
    zone_hops: int = 2
    # Causality-aware admission (post-submission hardening, see engine.py's `_fold_target`):
    # spatial nearness alone isn't enough -- an incident that has stopped alerting (`op.quiet`
    # exceeds this many seconds) stops absorbing new, spatially-nearby crossings, on the theory
    # that a crossing which shows up only after this incident's own propagation has gone cold is
    # more plausibly a second, unrelated attack reusing the same neighbourhood. Deliberately well
    # under engine.py's CLOSE_SAMPLES (30 s quiet before the incident closes outright): this gate
    # needs to fire while the incident is still open, or it would never have any effect before the
    # status check already excludes it. 10 s is a heuristic, not a physically-derived constant --
    # same caveat as zone_hops above.
    admission_window_s: float = 10.0
    # LIVE mode (Phase 13): Modbus ingestion from an external plant emulator. All AT_LIVE_*.
    live_host: str = "127.0.0.1"
    live_port: int = 5020
    live_tagmap: Path = Path("../config/tagmap.yaml")
    live_poll_s: float = 0.25  # one batched read per block every poll
    live_timeout_s: float = 1.0  # per request
    live_stale_after_s: float = 1.0  # no update within this: quality `stale`
    live_max_age_s: float = 5.0  # last-value-hold limit; older: quality `missing`
    live_frozen_after_s: float = 30.0  # a sensor reading identical this long while others move
    live_max_in_flight: int = 2
    live_block_gap: int = 8  # tags closer than this many registers share one read
    live_backoff_base_s: float = 0.25
    live_backoff_max_s: float = 5.0
    live_train_min: float = 20.0  # minutes of clean traffic recorded for the LIVE detector
    # Phase 3: the shared incident store + tamper-evident audit ledger for every mode (SIM, HAI,
    # LIVE alike), not just LIVE -- kept under its original LIVE-era name/default/env var
    # (AT_LIVE_DB) for continuity; see `app/evidence.py`'s module docstring for the migration note.
    live_db: Path = Path("../data/live_incidents.sqlite")
    live_include_bad_quality: bool = False  # True: stale/missing/out-of-range tags are scored too
    # Attacker tool (Phase 13 Part D): extra allowed write targets, beyond loopback and the
    # docker-compose service name, as a comma-separated list. Empty by default.
    attacker_allowlist: str = ""
    # Operator authentication (Production Transition Roadmap, Phase 1): real per-operator
    # identity + role for the isolate action, replacing the shared demo API key for that one
    # write. Empty secret = auth disabled; isolate falls back to trusting the client-supplied
    # operator name, exactly today's behavior. `operators` is a JSON list of
    # {"username","password_hash","role"} ("operator" can isolate, "analyst" cannot);
    # password_hash comes from `app.api.auth.hash_password`, never a plaintext password.
    # Empty + demo_mode: one built-in demo/demo operator, logged as a warning (same spirit as
    # the unset api_key path).
    auth_secret: str = ""
    auth_token_ttl_s: float = 8 * 3600.0
    operators: str = ""
    # Account lockout (post-submission hardening): `login_limiter` above already rate-limits by
    # client address, but an attacker rotating source IPs (or behind a shared NAT) could still
    # grind through a weak password against ONE account unbounded. This locks the targeted
    # *username* itself after `auth_lockout_threshold` consecutive failures, independent of who's
    # asking -- cleared on a successful login. Deliberately not tied to attack_rate_per_min or
    # login_rate_per_min: a different attack shape needs a different key (username, not client).
    auth_lockout_threshold: int = 5
    auth_lockout_s: float = 300.0
    # Tag-level historian (Phase 2 MVP): raw per-node samples across all modes, independent of
    # incident snapshots -- the engine itself only keeps a 5-minute in-memory ring buffer. Built
    # only on a true production start (no explicit `engine=` override), same convention as LIVE.
    history_db: Path = Path("../data/history.sqlite")
    history_retention_hours: float = 168.0  # 7 days
    # SOC/SIEM export (Phase 3 MVP): a JSON webhook POSTed on every incident status transition,
    # in every mode. Empty = off.
    siem_webhook_url: str = ""
    siem_webhook_timeout_s: float = 3.0
    # Ask AI: free-text Q&A grounded in this session's own incident/topology data (app/ai.py),
    # answered by a real Google Gemini API call. Empty key = disabled (503) -- this is the one
    # feature that makes a real external network call and costs real money per question, so it is
    # opt-in and independently rate-limited (ai_rate_per_min), never gated by attack_rate_per_min.
    # The key is read server-side only and never reaches the browser.
    ai_api_key: str = ""
    ai_model: str = "gemini-flash-lite-latest"
    ai_rate_per_min: int = 10
    ai_timeout_s: float = 20.0


def _from_env() -> dict[str, object]:
    values: dict[str, object] = {}
    for name in Settings.model_fields:
        raw = os.environ.get(ENV_PREFIX + name.upper())
        if raw is None:
            continue
        values[name] = json.loads(raw) if name == "cors_origins" else raw
    return values


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate(_from_env())
