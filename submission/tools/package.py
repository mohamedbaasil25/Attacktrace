"""Builds submission/AttackTrace_Submission.zip (stdlib only; run from the repo root).

Included: source, docs, slides, screenshots, evidence, reports/metrics.json, README.
Excluded: node_modules, virtualenvs, .env, raw HAI data, trained model caches, build output, caches.
Aborts without writing the zip if a secret-looking value or a forbidden file is found.
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "AttackTrace_Submission.zip"
PREFIX = "AttackTrace"

SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "dist", "test-results", "playwright-report", ".git", "_superseded", "_previous",
}
SKIP_PATHS = {"backend/models", "data/hai", "reports"}  # reports/metrics.json is re-added below
SKIP_SUFFIXES = {".pt", ".joblib", ".pyc", ".csv", ".gz", ".zip", ".egg-info", ".sqlite", ".sqlite-wal", ".sqlite-shm"}
SKIP_NAMES = {".env", "CLAUDE.md", "PLAN.md", "ENHANCE_PLAN.md", "LIVE_PLAN.md", "AttackTrace_Master_Prompt.md"}  # internal notes stay out
ALWAYS = ["reports/metrics.json", "reports/live_metrics.json", "reports/live_faults.json", "reports/live_soak.json"]
# Phase 14 B2: SIM/HAI retrain in seconds on first start, so they stay excluded (regenerated).
# LIVE calibration needs ~20 minutes of real plant traffic, which can't be sped up by more CPU, so
# its small (~1.5 MB) pretrained weights ship instead -- a judge gets working LIVE mode immediately.
ALWAYS_PREFIXES = ["backend/models/live"]
KEEP_EMPTY = {"backend/models/.gitkeep", "data/hai/.gitkeep", "reports/.gitkeep"}

SECRETS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+_\-]{12,}"),
]
TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".yml", ".yaml", ".toml", ".txt",
        ".css", ".html", ".example", ".cfg", ".mk", ""}


def wanted(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel in KEEP_EMPTY or rel in ALWAYS:
        return True
    if any(rel == p or rel.startswith(p + "/") for p in ALWAYS_PREFIXES):
        return True
    if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
        return False
    if any(rel == p or rel.startswith(p + "/") for p in SKIP_PATHS):
        return False
    return path.name not in SKIP_NAMES and path.suffix not in SKIP_SUFFIXES and path != OUT


def collect() -> list[Path]:
    files = [p for p in ROOT.rglob("*") if p.is_file() and wanted(p)]
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def scan(files: list[Path]) -> list[str]:
    hits = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.name.startswith(".env") and p.name != ".env.example":
            hits.append(f"{rel}: env file")
        if p.suffix in {".csv", ".gz"} or "data/hai/" in rel and not rel.endswith(".gitkeep"):
            hits.append(f"{rel}: raw dataset")
        if p.suffix in TEXT or p.name in {"Dockerfile", "Makefile"}:
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pat in SECRETS:
                m = pat.search(text)
                if m:
                    hits.append(f"{rel}: matches {pat.pattern[:30]} -> {m.group(0)[:12]}...")
    return hits


def main() -> int:
    files = collect()
    hits = scan(files)
    if hits:
        print("SECRET / FORBIDDEN CONTENT FOUND, zip not written:")
        print("\n".join(hits))
        return 1
    OUT.unlink(missing_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, f"{PREFIX}/{p.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        for n in names:
            print(n)
    print(f"\n{len(names)} files, zip size {OUT.stat().st_size:,} bytes ({OUT.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
