"""Production Readiness Roadmap: dependency/supply-chain scan.

Runs `pip-audit` against the backend's own environment and `npm audit` against the frontend,
writing both reports to one JSON file. `pip-audit` is deliberately NOT a committed dependency
(`pyproject.toml`'s `dev` extras stay pytest/pytest-asyncio/httpx/ruff/mypy only); this script
installs it transiently into whichever Python runs it, unless `--skip-install` says it is
already available. `npm audit` needs no install (npm ships it).

`python -m eval.dependency_scan`. Unlike the slow-drift evasion script, this one DOES gate:
it exits non-zero if either report shows a CRITICAL or HIGH severity finding.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger("attacktrace.eval.dependency_scan")

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
HIGH_SEVERITIES = {"CRITICAL", "HIGH", "critical", "high"}


def run_pip_audit(python: str, skip_install: bool) -> dict[str, Any]:
    if not skip_install:
        subprocess.run(
            [python, "-m", "pip", "install", "--quiet", "pip-audit"], check=True, cwd=BACKEND_DIR
        )
    result = subprocess.run(
        [python, "-m", "pip_audit", "--format", "json"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    try:
        return dict(json.loads(result.stdout or "{}"))
    except json.JSONDecodeError:
        return {"error": result.stderr or result.stdout, "returncode": result.returncode}


def run_npm_audit() -> dict[str, Any]:
    npm = shutil.which("npm") or "npm"  # Windows needs the resolved npm.cmd, not the bare name
    result = subprocess.run(
        [npm, "audit", "--json"],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
    )
    try:
        return dict(json.loads(result.stdout or "{}"))
    except json.JSONDecodeError:
        return {"error": result.stderr or result.stdout, "returncode": result.returncode}


def _pip_audit_severities(report: dict[str, Any]) -> list[str]:
    out = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            out.append(str(vuln.get("severity") or "UNKNOWN"))
    return out


def _npm_audit_severities(report: dict[str, Any]) -> list[str]:
    vulns = report.get("vulnerabilities", {})
    if isinstance(vulns, dict):
        return [str(v.get("severity")) for v in vulns.values() if isinstance(v, dict)]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    settings = get_settings()
    pip_report = run_pip_audit(args.python, args.skip_install)
    npm_report = run_npm_audit()

    out = Path(args.out) if args.out else settings.reports_dir / "dependency_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"python": pip_report, "npm": npm_report}, indent=1))

    pip_sev = _pip_audit_severities(pip_report)
    npm_sev = _npm_audit_severities(npm_report)
    log.info(
        "wrote %s: pip-audit findings=%d, npm audit findings=%d", out, len(pip_sev), len(npm_sev)
    )
    high = [s for s in pip_sev + npm_sev if s in HIGH_SEVERITIES]
    if high:
        log.warning("%d CRITICAL/HIGH severity finding(s): %s", len(high), high)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
