"""Production Readiness Roadmap: security pre-emption suite.

Three categories of deliberately adversarial checks that don't fit the existing
`test_security.py` (which covers the happy-path key/demo-mode/rate-limit contract):
tie-break gaming on `app.localize.locator.break_ties`, API fuzzing for clean 4xx (never
a 500 or a leaked stack trace), and rate-limit bypass attempts via X-Forwarded-For.
"""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.security import RateLimiter
from app.engine import Engine
from app.localize.locator import SIGNAL_RANK, TIE_FLOOR, TIE_ONSET, break_ties

from .test_security import KEY, make_client

# ----------------------------------------------------------------- tie-break gaming


def test_break_ties_cannot_be_gamed_into_picking_a_non_causal_winner() -> None:
    """A later-onset actuator with an inflated score/downstream-reach must not outrank a
    sensor whose onset is strictly earliest in the tie group."""
    # 0 = sensor S (true, earliest cause), 1 = actuator A (gamed: higher score, later onset,
    # inflated downstream reach), 2 = a third tie partner both could "reach".
    score = np.array([0.90, 0.95, 0.80])
    conf = np.array([0.45, 0.48, 0.40])
    onset = np.array([0, 1, 1])  # A is exactly TIE_ONSET samples behind S
    types = ["sensor", "actuator", "sensor"]
    downstream = [{1, 2}, {0, 2}, set()]  # A claims it reaches S and node 2 (gamed)

    new_order, _, _ = break_ties(score, conf, onset, types, downstream)

    assert onset[1] - onset[0] <= TIE_ONSET  # confirms A is in the near-tie group
    assert score[1] >= TIE_FLOOR * score[1]
    assert new_order[0] == 0  # S (earliest onset) must still win, despite A's higher score


def test_break_ties_enforces_signal_rank_when_onset_and_reach_are_equal() -> None:
    """With identical onset and identical downstream reach, sensor must outrank actuator
    even if the actuator's raw score is higher (SIGNAL_RANK: sensor < controller < actuator)."""
    score = np.array([0.85, 0.90])  # actuator scores higher...
    conf = np.array([0.45, 0.50])
    onset = np.array([2, 2])  # ...but onset is tied
    types = ["actuator", "sensor"]
    downstream = [set(), set()]  # ...and downstream reach is tied (both empty)

    new_order, _, _ = break_ties(score, conf, onset, types, downstream)

    assert SIGNAL_RANK["sensor"] < SIGNAL_RANK["actuator"]
    assert new_order.index(1) < new_order.index(0)  # sensor (index 1) ranks ahead of actuator


def test_break_ties_group_membership_boundary() -> None:
    """A candidate just below TIE_FLOOR, or just outside TIE_ONSET, must not be gameable
    into the near-tie group by score or onset alone."""
    best = 1.0
    just_under_floor = TIE_FLOOR * best - 1e-6
    score = np.array([best, just_under_floor, 0.0])
    conf = np.array([0.5, 0.3, 0.2])
    onset = np.array([0, 0, 0])
    types = ["sensor", "actuator", "sensor"]
    downstream = [set(), set(), set()]
    new_order, _, _ = break_ties(score, conf, onset, types, downstream)
    # The just-under-floor candidate keeps its original relative position among non-group
    # members (appended after the group, in original score order) rather than being pulled
    # into the winner's tie group.
    assert new_order[0] == 0
    assert 1 in new_order[1:]

    # Onset boundary: candidate 1 scores high enough but its onset is TIE_ONSET + 1 away.
    score2 = np.array([best, best])
    conf2 = np.array([0.5, 0.5])
    onset2 = np.array([0, TIE_ONSET + 1])
    types2 = ["sensor", "actuator"]
    downstream2 = [set(), set()]
    new_order2, _, _ = break_ties(score2, conf2, onset2, types2, downstream2)
    assert new_order2[0] == 0  # candidate 1 never enters the tie group despite equal score


# ----------------------------------------------------------------------- API fuzzing

ATTACK_PATH = "/api/attack"
ISOLATE_PATH = "/api/isolate"
MODE_PATH = "/api/mode"
AUTH = {"X-API-Key": KEY}


def _no_leaked_traceback(body: str) -> bool:
    lowered = body.lower()
    return "traceback" not in lowered and '.py"' not in lowered and "line " not in lowered


@pytest.fixture
def fuzz_client(engine: Engine, tmp_path: Path) -> TestClient:
    with make_client(engine, tmp_path) as c:
        yield c


ATTACK_FUZZ_BODIES = [
    {},
    {"scenario": "sensor_offset"},  # missing target
    {"scenario": "not_a_real_scenario", "target": "LIT101"},
    {"scenario": "sensor_offset", "target": "LIT101", "magnitude": "not-a-number"},
    {"scenario": "sensor_offset", "target": "LIT101", "duration_s": -5},
    {"scenario": "sensor_offset", "target": "LIT101", "duration_s": 999999},
    {"scenario": "sensor_offset", "target": "x" * 10000},
    {"scenario": "sensor_offset", "target": "LIT101\x00../../etc/passwd"},
    {"scenario": None, "target": None},
]


@pytest.mark.parametrize("body", ATTACK_FUZZ_BODIES)
def test_attack_fuzz_payloads_return_422_not_500(fuzz_client: TestClient, body: object) -> None:
    r = fuzz_client.post(ATTACK_PATH, json=body, headers=AUTH)
    assert r.status_code in (422, 409)  # 409 only possible in HAI mode, never reached here
    assert r.status_code != 500
    assert _no_leaked_traceback(r.text)


ISOLATE_FUZZ_BODIES = [
    {},
    {"incident_id": "inc_001"},  # missing node_id
    {"incident_id": "", "node_id": ""},
    {"incident_id": "inc_001", "node_id": "../../etc/passwd"},
    {"incident_id": "x" * 10000, "node_id": "LIT101"},
    {"incident_id": "inc_001", "node_id": "LIT101", "operator": "x" * 100000},
    {"incident_id": None, "node_id": None},
]


@pytest.mark.parametrize("body", ISOLATE_FUZZ_BODIES)
def test_isolate_fuzz_payloads_return_422_not_500(fuzz_client: TestClient, body: object) -> None:
    r = fuzz_client.post(ISOLATE_PATH, json=body, headers=AUTH)
    # Malformed/missing fields fail Pydantic validation (422); a well-typed but unknown
    # incident/node id is a clean 200 refusal via IsolateResponse(accepted=False, ...).
    assert r.status_code in (422, 200)
    assert r.status_code != 500
    assert _no_leaked_traceback(r.text)
    if r.status_code == 200:
        assert r.json()["accepted"] is False


MODE_FUZZ_BODIES = [
    {},
    {"mode": "not_a_real_mode"},
    {"mode": None},
    {"mode": 12345},
    {"mode": ["sim"]},
]


@pytest.mark.parametrize("body", MODE_FUZZ_BODIES)
def test_mode_fuzz_payloads_return_422_not_500(fuzz_client: TestClient, body: object) -> None:
    r = fuzz_client.post(MODE_PATH, json=body, headers=AUTH)
    assert r.status_code == 422
    assert _no_leaked_traceback(r.text)


def test_require_key_malformed_auth_headers(fuzz_client: TestClient) -> None:
    body = {"mode": "sim"}
    malformed_headers = [
        {"X-API-Key": ""},
        {"X-API-Key": "x" * 100000},
        {"X-API-Key": "line1\nline2"},
        {"X-API-Key": "wrong-key-but-right-length-" + "x" * len(KEY)},
    ]
    for headers in malformed_headers:
        r = fuzz_client.post(MODE_PATH, json=body, headers=headers)
        assert r.status_code == 401
        assert r.status_code != 500
        assert _no_leaked_traceback(r.text)

    # Header names are case-insensitive per HTTP/Starlette -- the correct key must still work
    # regardless of casing (guards a future regression that only checks one exact casing).
    r_ok = fuzz_client.post(MODE_PATH, json=body, headers={"x-Api-KEY": KEY})
    assert r_ok.status_code == 200


# ------------------------------------------------------------------- rate-limit bypass


def test_rate_limit_bypass_via_forwarded_header_without_trust_proxy(
    engine: Engine, tmp_path: Path
) -> None:
    """With trust_proxy off (default), spoofing a fresh X-Forwarded-For on every request must
    not grant a fresh quota -- the limiter must key on the socket peer, not the header."""
    with make_client(engine, tmp_path, attack_rate_per_min=2) as c:
        body = {"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25}
        for i in range(2):
            r = c.post(ATTACK_PATH, json=body, headers={**AUTH, "X-Forwarded-For": f"1.2.3.{i}"})
            assert r.status_code == 200
        r3 = c.post(ATTACK_PATH, json=body, headers={**AUTH, "X-Forwarded-For": "9.9.9.9"})
        assert r3.status_code == 429  # a new spoofed XFF value did not reset the bucket


def test_rate_limit_bypass_via_forwarded_for_list_with_trust_proxy_on(
    engine: Engine, tmp_path: Path
) -> None:
    """With trust_proxy on, the limiter trusts the leftmost XFF entry (RFC 7239): the SAME
    leftmost value across requests must share one bucket (no bypass by reordering/padding the
    list), while a genuinely different leftmost value is, by design, a different bucket --
    this is a documented trust boundary for deployments behind a controlled reverse proxy,
    not a public-facing passthrough."""
    with make_client(engine, tmp_path, attack_rate_per_min=1, trust_proxy=True) as c:
        body = {"scenario": "sensor_offset", "target": "LIT101", "magnitude": -25}
        h = {**AUTH, "X-Forwarded-For": "5.5.5.5, proxy1, proxy2"}
        assert c.post(ATTACK_PATH, json=body, headers=h).status_code == 200
        # Same leftmost client, different padding after it: still the same bucket -> blocked.
        h_repad = {**AUTH, "X-Forwarded-For": "5.5.5.5,  proxy3 ,proxy4,proxy5"}
        assert c.post(ATTACK_PATH, json=body, headers=h_repad).status_code == 429


def test_rate_limiter_window_boundary_exactness() -> None:
    """White-box check of the sliding-window arithmetic: exactly `limit` requests fit inside
    the window, the (limit+1)th is blocked, and a hit exactly WINDOW_S old is expired."""
    now = [0.0]
    rl = RateLimiter(3, clock=lambda: now[0])
    assert rl.check("c") is None
    assert rl.check("c") is None
    assert rl.check("c") is None
    assert rl.check("c") is not None  # 4th request inside the window is blocked

    now[0] = 60.0  # exactly WINDOW_S after the first hit: must be expired, not off-by-one
    assert rl.check("c") is None
