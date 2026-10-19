# PowerShell equivalent of `make live-train`. Needs the emulator running (scripts\emulator.ps1).
# Records AT_LIVE_TRAIN_MIN minutes of clean live traffic (real time, ~20 min by default).
. "$PSScriptRoot\_common.ps1"
Push-Location (Join-Path $RepoRoot "backend")
try { & $Py -m app.live.train } finally { Pop-Location }
