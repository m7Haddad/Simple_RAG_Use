#!/usr/bin/env bash
# Starts the backend (http://127.0.0.1:8000) and the frontend (http://127.0.0.1:5173).
# Press Ctrl+C to stop both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"   # Git Bash on Windows

if [ ! -x "$PY" ]; then
  echo "Python virtual environment not found at .venv. Follow the setup steps in README.md." >&2
  exit 1
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Frontend dependencies missing. Run: cd frontend && npm install" >&2
  exit 1
fi

(cd "$ROOT/backend" && exec "$PY" -m app) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

echo "Backend  -> http://127.0.0.1:8000  (API docs at /docs)"
echo "Frontend -> http://127.0.0.1:5173"
cd "$ROOT/frontend"
npm run dev
