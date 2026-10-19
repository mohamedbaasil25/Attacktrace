# PowerShell equivalent of `make preflight`.
. "$PSScriptRoot\_common.ps1"
& $Py (Join-Path $RepoRoot "scripts\preflight.py")
exit $LASTEXITCODE
