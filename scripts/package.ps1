# PowerShell equivalent of `make package`.
. "$PSScriptRoot\_common.ps1"
Push-Location $RepoRoot
try { & $Py submission\tools\package.py } finally { Pop-Location }
