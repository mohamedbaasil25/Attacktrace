"""Ask AI's one real-network-call gap (see the "What We Didn't Solve" doc): `test_ai.py` always
monkeypatches the Gemini client, so nothing in the normal suite ever proves the real API call
still works end to end -- a wire-format change in `google-genai`, a renamed/retired model, or a
revoked key would only surface live, during a demo.

This file closes that gap WITHOUT making the normal suite depend on network access or a paid key:
it runs only when AT_AI_API_KEY is actually set in the environment (a real key, not the test
suite's usual `Settings(ai_api_key="test-key")` stand-in), and is skipped otherwise -- `make test`
and CI stay fully offline and deterministic by default. Run it deliberately before a demo:

    AT_AI_API_KEY=<real key> .venv/Scripts/python -m pytest tests/test_ai_live_smoke.py -q
"""

import os

import pytest

from app.ai import build_context, generate_answer
from app.config import get_settings
from app.engine import Engine
from app.runtime import Runtime
from app.schemas import AttackRequest

REAL_KEY = os.environ.get("AT_AI_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not REAL_KEY, reason="set a real AT_AI_API_KEY to run the live Ask AI smoke test"
)


def test_generate_answer_against_the_real_gemini_api() -> None:
    settings = get_settings()
    context = {
        "mode": "sim",
        "uptime_s": 120.0,
        "incidents": [
            {
                "id": "inc_smoke",
                "status": "open",
                "explanation": "Origin LIT101 (sensor) spoof low -> T1 overflow risk",
                "action": "Isolate LIT101",
            }
        ],
    }
    answer = generate_answer("What is the origin node, in one word?", context, settings)
    assert isinstance(answer, str) and answer.strip()
    assert "LIT101" in answer  # it must actually ground on the context, not free-associate


def test_build_context_feeds_a_real_call_without_error(engine: Engine) -> None:
    """build_context's REAL output (not the hand-built dict above) round-tripped through a real
    call -- catches a schema drift between the two that a mocked test would miss."""
    engine.launch(AttackRequest(scenario="actuator_force", target="P101", magnitude=0))
    for _ in range(240):
        engine.step_sample()
    rt: Runtime = engine
    context = build_context(rt)
    assert context["incidents"], "the attack above should have opened an incident"
    answer = generate_answer("Is there an active incident right now?", context, get_settings())
    assert isinstance(answer, str) and answer.strip()
