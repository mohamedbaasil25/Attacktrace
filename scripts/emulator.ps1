# PowerShell equivalent of `make emulator`.
. "$PSScriptRoot\_common.ps1"
Push-Location $RepoRoot
try { & $Py -m plant_emulator } finally { Pop-Location }
