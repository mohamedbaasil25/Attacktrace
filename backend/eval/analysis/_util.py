"""Shared helpers for the Part A analysis scripts: no eval-behaviour code lives here."""

import json
import math
from pathlib import Path

from app.config import get_settings

Z95 = 1.959963984540054  # two-sided 95% normal quantile


def wilson(k: int, n: int, z: float = Z95) -> dict[str, float | int]:
    """Wilson score 95% interval for a proportion k/n. n=0 -> a degenerate 0..1 interval."""
    if n == 0:
        return {"k": k, "n": n, "p": 0.0, "lo": 0.0, "hi": 1.0}
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return {
        "k": k,
        "n": n,
        "p": p,
        "lo": max(0.0, (center - half) / denom),
        "hi": min(1.0, (center + half) / denom),
    }


def analysis_path() -> Path:
    settings = get_settings()
    return settings.reports_dir / "fix_analysis.json"


def reports_dir() -> Path:
    return get_settings().reports_dir


def merge_write(key: str, data: object) -> Path:
    """Read-modify-write one top-level key of reports/fix_analysis.json; other keys untouched."""
    path = analysis_path()
    existing: dict[str, object] = json.loads(path.read_text()) if path.exists() else {}
    existing[key] = data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=1))
    return path


def final_analysis_path() -> Path:
    return get_settings().reports_dir / "final_analysis.json"


def merge_write_final(key: str, data: object) -> Path:
    """Phase 16: read-modify-write one top-level key of reports/final_analysis.json (kept
    separate from fix_analysis.json per the Phase 16 prompt's rule 1); other keys untouched."""
    path = final_analysis_path()
    existing: dict[str, object] = json.loads(path.read_text()) if path.exists() else {}
    existing[key] = data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=1))
    return path
