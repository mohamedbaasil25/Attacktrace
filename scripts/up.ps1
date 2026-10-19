# PowerShell equivalent of `make up`. No venv needed -- Docker does the building.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try { docker compose up --build } finally { Pop-Location }
