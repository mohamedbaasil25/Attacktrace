# PowerShell equivalent of `make dev`: backend on :8000 (background), frontend on :5173 (foreground).
# Ctrl+C stops the frontend; the backend process is stopped when this script's own process exits
# (close the window) or by killing the PID this script prints.
. "$PSScriptRoot\_common.ps1"

Push-Location (Join-Path $RepoRoot "backend")
$backend = Start-Process -FilePath $Py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000" `
    -PassThru -NoNewWindow
Pop-Location
Write-Host "backend started (PID $($backend.Id)) -- http://localhost:8000"

Push-Location (Join-Path $RepoRoot "frontend")
try {
    npm run dev
} finally {
    Pop-Location
    if (-not $backend.HasExited) {
        Write-Host "stopping backend (PID $($backend.Id))"
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
