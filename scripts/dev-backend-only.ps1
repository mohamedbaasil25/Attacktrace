. "$PSScriptRoot\_common.ps1"
Set-Location (Join-Path $RepoRoot "backend")
$env:AT_AUTH_SECRET = "dev-verify-secret-not-for-production"
& $Py -m uvicorn app.main:app --port 8000
