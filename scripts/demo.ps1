# PowerShell equivalent of `make demo`.
. "$PSScriptRoot\_common.ps1"
& $Py (Join-Path $RepoRoot "scripts\demo.py")
exit $LASTEXITCODE
