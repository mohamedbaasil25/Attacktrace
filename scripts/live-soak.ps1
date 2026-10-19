# PowerShell equivalent of `make live-soak`. Spawns and kills its own emulator subprocess; do not
# run scripts\emulator.ps1 first. Real time: about 1 h with the defaults. Writes
# reports\live_soak.json.
. "$PSScriptRoot\_common.ps1"
Push-Location (Join-Path $RepoRoot "backend")
try { & $Py -m eval.live_soak } finally { Pop-Location }
