# PowerShell equivalent of `make demo-trials`. SIM is fast; LIVE needs the emulator running and a
# trained LIVE model, and takes ~8-9 hours in real time for the full 150 trials.
. "$PSScriptRoot\_common.ps1"
Push-Location (Join-Path $RepoRoot "backend")
try { & $Py -m eval.demo_trials @args } finally { Pop-Location }
