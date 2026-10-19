# PowerShell equivalent of `make eval-live`. Needs the emulator running and a trained LIVE model.
# Real time: about 2.75 h with the defaults. Writes reports\live_metrics.json.
. "$PSScriptRoot\_common.ps1"
Push-Location (Join-Path $RepoRoot "backend")
try { & $Py -m eval.live } finally { Pop-Location }
