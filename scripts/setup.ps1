# PowerShell equivalent of `make setup`.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $RepoRoot "backend")
try {
    py -3.11 -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
} finally {
    Pop-Location
}

Push-Location (Join-Path $RepoRoot "frontend")
try {
    npm ci
} finally {
    Pop-Location
}
