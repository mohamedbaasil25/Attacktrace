"""Lay out the one-page incident report from an `Incident` and the worst impact values seen."""

from datetime import UTC, datetime

from app.report.pdf import Page, text_width, wrap
from app.schemas import Impact, Incident

MARGIN = 40.0
BODY = 9.0
GRAYS = (0.15, 0.55, 0.85)  # deviation, onset, causal: dark, mid, light (also numbered in text)


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _eta(v: float | None) -> str:
    return "none" if v is None else f"{v:.0f} s"


def render_report(inc: Incident, impact: Impact | None, mode: str, generated_at: float) -> bytes:
    pg = Page()
    right = pg.w - MARGIN
    width = right - MARGIN
    y = MARGIN + 14

    def heading(label: str) -> None:
        nonlocal y
        y += 8
        pg.text(MARGIN, y, label, 11, bold=True)
        y += 4
        pg.hline(MARGIN, right, y)
        y += 13

    def para(s: str, size: float = BODY, bold: bool = False) -> None:
        nonlocal y
        for line in wrap(s, size, width):
            pg.text(MARGIN, y, line, size, bold)
            y += size + 3

    pg.text(MARGIN, y, "AttackTrace incident report", 17, bold=True)
    y += 16
    meta = (
        f"{inc.id}  |  status {inc.status}  |  {mode.upper()} mode  |  "
        f"detected {_utc(inc.detected_at)}"
    )
    para(meta, BODY)

    top = inc.origin[0]
    heading("Origin")
    label = f"{top.id} ({top.type})  confidence {top.confidence * 100:.0f}%"
    pg.text(MARGIN, y, label, 14, bold=True)
    y += 17
    if inc.ambiguous:
        para(
            "AMBIGUOUS: top two candidates are close. Treat the top 3 as equally likely.",
            BODY,
            True,
        )
    para(f"{inc.mitre} {inc.mitre_name}" if inc.mitre else "MITRE ATT&CK: not mapped (HAI data)")

    heading("Ranked candidates (score breakdown)")
    bar_x, bar_w = MARGIN + 230, 120.0
    pg.text(bar_x, y + 2, "bar: deviation | onset | causal", 7.5)
    y += 14
    for rank, c in enumerate(inc.origin[:3], start=1):
        pg.text(MARGIN, y, f"{rank}. {c.id} ({c.type})  {c.confidence * 100:.0f}%", BODY)
        b = c.breakdown
        if b is not None:
            total = (b.deviation + b.onset + b.causal) or 1.0
            x = bar_x
            for part, gray in zip((b.deviation, b.onset, b.causal), GRAYS, strict=True):
                seg = bar_w * part / total
                if seg > 0:
                    pg.rect(x, y - 8, seg, 9, gray=gray, line=True)
                x += seg
            pg.text(
                bar_x + bar_w + 8,
                y,
                f"{b.deviation:.2f} | {b.onset:.2f} | {b.causal:.2f}",
                8,
            )
        y += 15
    w = top.weights
    if w is not None:
        para(
            f"Weights: deviation {w.deviation:.1f}, onset {w.onset:.1f}, causal {w.causal:.1f}. "
            "Bar segments are weight x signal, as numbers on the right.",
            8,
        )

    heading("Propagation path (seconds after first onset)")
    steps = "  >  ".join(f"{s.id} +{s.t:.1f}s" for s in inc.path) or "no path"
    para(steps)

    heading("Timeline")
    first = _utc(inc.detected_at)
    para(
        f"Detected {first}. Path spans {inc.path[-1].t:.1f} s from first onset."
        if inc.path
        else f"Detected {first}."
    )
    contained_at = getattr(inc, "contained_at", None)
    if inc.status == "contained" and contained_at is not None:
        after = float(contained_at) - inc.detected_at
        para(f"Contained {_utc(float(contained_at))} ({after:.0f} s after detection).")
    elif inc.status == "closed":
        para("Closed after 30 s without alerts. No isolate action recorded.")
    else:
        para("Not contained. No isolate action recorded.")
    if inc.isolated_by:
        para(f"Isolated by {inc.isolated_by}.")

    heading("Explanation and action")
    para(inc.explanation)
    para(inc.action, BODY, True)

    heading("Impact (worst values seen)")
    if impact is None:
        para("Not available in this mode.")
    else:
        para(
            f"T1 overflow {_eta(impact.t1_overflow_s)}, T1 dry-run {_eta(impact.t1_dry_s)}, "
            f"T2 overflow {_eta(impact.t2_overflow_s)}, T2 dry-run {_eta(impact.t2_dry_s)}."
        )
        stress = ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(impact.pump_stress.items()))
        para(f"Pump stress: {stress}. Energy wasted: {impact.energy_wasted_kwh:.3f} kWh.")

    heading("Baseline comparison")
    n = len(inc.baseline_alarms)
    names = ", ".join(inc.baseline_alarms) or "none"
    para(
        f"A 3-sigma baseline raised {n} alarm{'s' if n != 1 else ''}: {names}. "
        "AttackTrace reports one origin."
    )

    pg.hline(MARGIN, right, pg.h - 38)
    foot = f"Generated {_utc(generated_at)}. Values come from the live run; none are estimated."
    pg.text(MARGIN, pg.h - 26, foot, 7.5)
    assert y < pg.h - 45, f"report overflows the page (y={y:.0f})"
    _ = text_width  # re-exported for tests
    return pg.build()
