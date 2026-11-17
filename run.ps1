# Starts the backend (http://127.0.0.1:8000) and the frontend (http://127.0.0.1:5173).
# Press Ctrl+C to stop both.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Python virtual environment not found at .venv. Follow the setup steps in README.md." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "Frontend dependencies missing. Run: cd frontend; npm install" -ForegroundColor Red
    exit 1
}

$backend = Start-Process -FilePath $python -ArgumentList "-m", "app" -WorkingDirectory (Join-Path $root "backend") -NoNewWindow -PassThru
Write-Host "Backend  -> http://127.0.0.1:8000  (API docs at /docs)" -ForegroundColor Green
Write-Host "Frontend -> http://127.0.0.1:5173" -ForegroundColor Green
try {
    Push-Location (Join-Path $root "frontend")
    npm run dev
}
finally {
    Pop-Location
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
}
