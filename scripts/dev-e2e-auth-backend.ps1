# Phase 4: a dedicated backend instance, auth-enabled, for e2e/auth.spec.ts -- separate port and
# separate incidents DB from the normal dev stack so this never touches the smoke-spec server.
. "$PSScriptRoot\_common.ps1"
Set-Location (Join-Path $RepoRoot "backend")
$env:AT_PORT = "8010"
$env:AT_AUTH_SECRET = "e2e-auth-spec-secret-not-for-production"
$env:AT_OPERATORS = '[{"username":"opuser","password_hash":"1291e4d04d130a4ef4ee48a75ca9c98a$7f2e2eb8d4ffa240d2bde4110ac5f313d9ee00430908e95c4a9be652cfe08c30","role":"operator"},{"username":"anuser","password_hash":"a9939c94575595b649680cd0c149d0ec$1d20c03fafe02fbb88dc51ecc93d0581eb9337294e60acf17c866b4a7b20233f","role":"analyst"}]'
$env:AT_LIVE_DB = "../data/e2e_auth_incidents.sqlite"
& $Py -m uvicorn app.main:app --port 8010
