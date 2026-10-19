# Phase 14 B7: shared setup for the PowerShell equivalents of the Makefile's targets.
# Dot-sourced by every script in this directory: `. "$PSScriptRoot\_common.ps1"`.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "No venv at backend\.venv -- run scripts\setup.ps1 first."
}
