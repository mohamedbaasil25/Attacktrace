from pathlib import Path
from typing import Any

import pytest

import eval.run as eval_run
from app.config import Settings
from app.main import ensure_metrics


def test_first_start_writes_metrics_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[Settings] = []

    def fake(s: Settings) -> dict[str, Any]:
        calls.append(s)
        (s.reports_dir / "metrics.json").write_text("{}")
        return {}

    monkeypatch.setattr(eval_run, "write_metrics", fake)
    settings = Settings(reports_dir=tmp_path / "reports", hai_dir=tmp_path / "no-hai")
    (tmp_path / "reports").mkdir()

    assert ensure_metrics(settings) is True  # missing -> evaluated
    assert ensure_metrics(settings) is False  # present -> left alone
    assert len(calls) == 1


def test_existing_metrics_are_never_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(eval_run, "write_metrics", lambda s: pytest.fail("must not run"))
    (tmp_path / "metrics.json").write_text('{"keep": true}')
    assert ensure_metrics(Settings(reports_dir=tmp_path, hai_dir=tmp_path / "no-hai")) is False
    assert (tmp_path / "metrics.json").read_text() == '{"keep": true}'


def test_metrics_missing_the_hai_section_are_refreshed_once_data_appears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hai_dir: Path
) -> None:
    calls: list[int] = []

    def fake(s: Settings) -> dict[str, Any]:
        calls.append(1)
        (s.reports_dir / "metrics.json").write_text('{"hai": {}}')
        return {}

    monkeypatch.setattr(eval_run, "write_metrics", fake)
    (tmp_path / "metrics.json").write_text('{"detection": {}}')  # written before HAI existed
    settings = Settings(reports_dir=tmp_path, hai_dir=hai_dir)
    assert ensure_metrics(settings) is True  # SIM-only file + HAI data -> refresh
    assert ensure_metrics(settings) is False  # now has a "hai" section
    assert len(calls) == 1


def test_a_failing_metrics_step_never_stops_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: an OSError reading the optional HAI data inside the first-start metrics step
    ("Bad address" on a Docker Desktop bind mount) killed the whole app, SIM included."""
    from app import main as app_main

    def boom(settings: Settings) -> bool:
        raise OSError(14, "Bad address")

    monkeypatch.setattr(app_main, "ensure_metrics", boom)
    assert app_main.safe_ensure_metrics(Settings(reports_dir=tmp_path)) is False  # no exception
