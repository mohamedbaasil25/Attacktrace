"""Ask AI: free-text Q&A answered by a real Google Gemini API call, strictly grounded in
this session's own, already-computed incident/topology data (the same facts /api/incidents and
/api/topology already expose) -- never a general-purpose chatbot, and never given write access to
anything. The API key is read from AT_AI_API_KEY server-side only and never reaches the browser
(see app/api/rest.py's post_ask_ai, which is the only caller of `generate_answer` below).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.runtime import Runtime

log = logging.getLogger("attacktrace")

SYSTEM_PROMPT = (
    "You are Ask AI, embedded in AttackTrace, an industrial control system (ICS) security "
    "monitoring tool. Answer the operator's question using ONLY the JSON context below, which is "
    "this tool's own real, already-computed detection/localization output for the plant it is "
    "currently monitoring.\n"
    "Rules:\n"
    "1. Never invent a sensor value, incident, timestamp, or confidence number that is not in the "
    "context.\n"
    "2. If the context does not contain the answer, say plainly that you don't have that "
    "information -- do not guess.\n"
    "3. You cannot take any action on the plant: you cannot isolate equipment, change mode, or "
    "launch or stop an attack. If asked to do one of those, explain that the operator must use "
    "the Isolate button or the Attack Console themselves.\n"
    "4. Be concise: a few sentences, not an essay."
)


class AiNotConfiguredError(RuntimeError):
    """AT_AI_API_KEY is not set; the caller should answer 503, not 500."""


class AiRequestFailedError(RuntimeError):
    """The Gemini API call itself failed (network, timeout, API error); the caller should answer
    502 with a generic message -- never the raw exception, which could echo request internals."""


def build_context(rt: Runtime) -> dict[str, Any]:
    """Every currently-known incident, minus `ground_truth` -- the simulator's injected answer
    key, which exists only for the UI's own after-the-fact Reveal control. Leaving it out keeps
    the assistant talking about what the detector actually found, not the planted truth."""
    return {
        "mode": rt.mode,
        "uptime_s": round(rt.uptime_s, 1),
        "incidents": [
            inc.model_dump(exclude={"ground_truth"}, exclude_none=True) for inc in rt.incidents
        ],
    }


def generate_answer(question: str, context: dict[str, Any], settings: Settings) -> str:
    if not settings.ai_api_key:
        raise AiNotConfiguredError("AT_AI_API_KEY is not set")
    from google import genai  # imported lazily: optional dependency, only needed when configured
    from google.genai import types

    client = genai.Client(
        api_key=settings.ai_api_key,
        http_options=types.HttpOptions(timeout=int(settings.ai_timeout_s * 1000)),
    )
    try:
        response = client.models.generate_content(
            model=settings.ai_model,
            contents=f"Context (JSON):\n{json.dumps(context)}\n\nQuestion: {question}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=500,
            ),
        )
    except Exception as exc:  # google.genai.errors.APIError, timeouts, connection errors, etc.
        log.warning("Ask AI request failed: %s", exc)
        raise AiRequestFailedError(str(exc)) from exc
    return (response.text or "").strip() or "The model returned no answer."
