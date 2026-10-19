# PowerShell equivalent of `make test`.
. "$PSScriptRoot\_common.ps1"

Push-Location (Join-Path $RepoRoot "backend")
try {
    & $Py -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Push-Location (Join-Path $RepoRoot "frontend")
try {
    npm test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
