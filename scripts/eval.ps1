# PowerShell equivalent of `make eval`.
. "$PSScriptRoot\_common.ps1"
Push-Location (Join-Path $RepoRoot "backend")
try { & $Py -m eval.run } finally { Pop-Location }
