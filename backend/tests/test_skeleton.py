import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.main import app


def test_app_builds() -> None:
    assert isinstance(app, FastAPI)
    assert app.title == "AttackTrace"


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AT_SEED", "7")
    get_settings.cache_clear()
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.seed == 7
    assert abs(s.w_deviation + s.w_onset + s.w_causal - 1.0) < 1e-9
    get_settings.cache_clear()
