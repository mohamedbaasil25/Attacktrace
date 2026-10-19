"""Phase 11 B6: the one-page PDF report."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.attacks import Scenario
from app.engine import Engine, worst_impact
from app.main import create_app
from app.report import render_report
from app.report.pdf import Page, ascii_text, wrap
from app.schemas import AttackRequest, Impact

TEST_KEY = "test-key-123456"  # pragma: allowlist secret


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(engine, run_loop=False)
    app.state.reports_dir = tmp_path
    app.state.hai_dir = tmp_path / "no-hai"
    with TestClient(app) as c:
        yield c


def with_incident(engine: Engine) -> str:
    for _ in range(120):
        engine.step_sample()
    engine.launch(AttackRequest(scenario=Scenario.ACTUATOR_FORCE, target="P101"))
    for _ in range(40):
        engine.step_sample()
    return engine.incidents[0].id


def check_structure(pdf: bytes) -> None:
    """Header, trailer, one page, and every xref offset points at its object."""
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", pdf)) == 1
    assert b"/Count 1" in pdf
    start = int(re.search(rb"startxref\n(\d+)", pdf).group(1))  # type: ignore[union-attr]
    table = pdf[start:].split(b"\n")
    n = int(table[1].split()[1])
    for i in range(1, n):
        off = int(table[2 + i].split()[0])
        assert pdf[off:].startswith(b"%d 0 obj" % i)
    length = int(re.search(rb"/Length (\d+)", pdf).group(1))  # type: ignore[union-attr]
    body = pdf.split(b"stream\n", 1)[1]
    assert body[length : length + len(b"\nendstream")] == b"\nendstream"


def test_report_endpoint_returns_a_valid_one_page_pdf(client: TestClient, engine: Engine) -> None:
    inc_id = with_incident(engine)
    r = client.get(f"/api/incidents/{inc_id}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert inc_id in r.headers["content-disposition"]
    check_structure(r.content)
    text = r.content.decode("latin-1")
    inc = engine.incidents[0]
    for needle in (inc.id, inc.origin[0].id, inc.mitre, "Ranked candidates", "Propagation path"):
        assert needle in text
    assert "Origin" in text and "Impact" in text and "Baseline comparison" in text


def test_unknown_incident_is_404(client: TestClient) -> None:
    assert client.get("/api/incidents/inc_999/report.pdf").status_code == 404


def test_report_is_open_without_a_key(engine: Engine, tmp_path: Path) -> None:
    from app.config import Settings

    app = create_app(engine, run_loop=False)
    app.state.settings = Settings(api_key=TEST_KEY)
    app.state.hai_dir = tmp_path / "no-hai"
    inc_id = with_incident(engine)
    with TestClient(app) as c:
        assert c.get(f"/api/incidents/{inc_id}/report.pdf").status_code == 200  # read-only


def test_report_shows_the_ambiguous_banner_and_breakdown(engine: Engine) -> None:
    inc_id = with_incident(engine)
    inc = engine.incidents[0].model_copy(update={"ambiguous": True})
    pdf = render_report(inc, engine.incident_impact.get(inc_id), "sim", 0.0)
    check_structure(pdf)
    assert b"AMBIGUOUS" in pdf and b"deviation | onset | causal" in pdf


def test_impact_snapshot_keeps_the_worst_values(engine: Engine) -> None:
    inc_id = with_incident(engine)
    snap = engine.incident_impact[inc_id]
    mild = Impact(
        t1_overflow_s=None,
        t1_dry_s=None,
        t2_overflow_s=None,
        t2_dry_s=None,
        pump_stress={},
        energy_wasted_kwh=0.0,
    )
    merged = worst_impact(snap, mild)
    assert merged.energy_wasted_kwh == snap.energy_wasted_kwh
    assert merged.t1_overflow_s == snap.t1_overflow_s  # a later "none" never hides a worse ETA
    a = mild.model_copy(update={"t1_overflow_s": 90.0})
    b = mild.model_copy(update={"t1_overflow_s": 40.0})
    assert worst_impact(a, b).t1_overflow_s == 40.0


def test_pdf_text_helpers() -> None:
    assert ascii_text("A → B · 3" + chr(0x3C3)) == "A -> B - 3sigma"
    lines = wrap("word " * 80, 9, 200)
    assert len(lines) > 1 and all(len(ln) * 9 * 0.56 <= 200 + 9 * 0.56 * 6 for ln in lines)
    page = Page()
    page.text(10, 10, r"a (paren) \ slash")
    assert rb"\(paren\)" in page.build()
