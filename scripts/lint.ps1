# PowerShell equivalent of `make lint`.
. "$PSScriptRoot\_common.ps1"

Push-Location (Join-Path $RepoRoot "backend")
try {
    & $Py -m ruff check . ..\plant_emulator ..\attacker
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Py -m ruff format --check . ..\plant_emulator ..\attacker
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Py -m mypy --strict app eval ..\plant_emulator
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Py -m mypy --strict ..\attacker
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Push-Location (Join-Path $RepoRoot "frontend")
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
