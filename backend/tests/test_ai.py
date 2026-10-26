"""Ask AI: grounding (app/ai.py) and the /api/ai/ask endpoint's wiring (gating, rate limit,
error mapping) -- never a real network call in tests, which always monkeypatch the model call."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai import AiNotConfiguredError, AiRequestFailedError, build_context, generate_answer
from app.api.security import RateLimiter
from app.config import Settings
from app.engine import Engine
from app.main import create_app
from app.runtime import Runtime
from app.schemas import AttackRequest


def make_client(engine: Engine, tmp_path: Path, **overrides: object) -> TestClient:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    settings = Settings(**overrides)  # type: ignore[arg-type]
    app.state.settings = settings
    app.state.ai_limiter = RateLimiter(settings.ai_rate_per_min)
    return TestClient(app)


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(engine, tmp_path) as c:
        yield c


# ---------------------------------------------------------------------------- app/ai.py directly
def test_build_context_excludes_ground_truth(engine: Engine) -> None:
    engine.launch(AttackRequest(scenario="actuator_force", target="P101", magnitude=0))
    for _ in range(240):
        engine.step_sample()
    rt: Runtime = engine
    ctx = build_context(rt)
    assert ctx["mode"] == "sim"
    assert ctx["incidents"], "the attack above should have opened an incident"
    for inc in ctx["incidents"]:
        assert "ground_truth" not in inc


def test_generate_answer_requires_a_key() -> None:
    with pytest.raises(AiNotConfiguredError):
        generate_answer("What is the origin?", {"incidents": []}, Settings())


def test_generate_answer_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    class FakeModels:
        def generate_content(self, **kwargs: Any) -> Any:
            assert "LIT101" in kwargs["contents"]  # context reached the prompt
            return SimpleNamespace(text="MV101 is the origin.")

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    answer = generate_answer(
        "What is the origin?", {"incidents": ["LIT101"]}, Settings(ai_api_key="test-key")
    )
    assert answer == "MV101 is the origin."


def test_generate_answer_wraps_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    class FakeModels:
        def generate_content(self, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    with pytest.raises(AiRequestFailedError):
        generate_answer("question", {}, Settings(ai_api_key="test-key"))


# ---------------------------------------------------------------------------- the endpoint
def test_ask_ai_is_503_when_not_configured(client: TestClient) -> None:
    r = client.post("/api/ai/ask", json={"question": "What is happening?"})
    assert r.status_code == 503
    assert "AT_AI_API_KEY" in r.json()["detail"]


def test_ask_ai_question_is_validated(client: TestClient) -> None:
    assert client.post("/api/ai/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ai/ask", json={"question": "x" * 501}).status_code == 422


def test_ask_ai_success(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.rest.generate_answer", lambda q, ctx, settings: "the answer")
    with make_client(engine, tmp_path, ai_api_key="test-key") as c:
        r = c.post("/api/ai/ask", json={"question": "What is the origin?"})
        assert r.status_code == 200
        assert r.json() == {"answer": "the answer"}


def test_ask_ai_maps_request_failure_to_502(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_failed(q: str, ctx: dict[str, Any], settings: Settings) -> str:
        raise AiRequestFailedError("network down")

    monkeypatch.setattr("app.api.rest.generate_answer", raise_failed)
    with make_client(engine, tmp_path, ai_api_key="test-key") as c:
        r = c.post("/api/ai/ask", json={"question": "What is the origin?"})
        assert r.status_code == 502


def test_ask_ai_is_rate_limited(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.rest.generate_answer", lambda q, ctx, settings: "ok")
    with make_client(engine, tmp_path, ai_api_key="test-key", ai_rate_per_min=2) as c:
        codes = [c.post("/api/ai/ask", json={"question": "q"}).status_code for _ in range(4)]
        assert codes == [200, 200, 429, 429]
