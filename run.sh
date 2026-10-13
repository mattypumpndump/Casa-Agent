#!/usr/bin/env bash
# One-command start: creates the venv, installs deps, writes .env if missing,
# starts the server and opens the browser. Re-run any time.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and re-run."; exit 1
fi

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m playwright install chromium >/dev/null 2>&1 || true

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — add your ANTHROPIC_API_KEY there later for the full agent."
fi

PORT=${PORT:-8000}
echo "Starting Casa Agent at http://127.0.0.1:$PORT  (Ctrl+C to stop)"
( sleep 2; open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null || true ) &
python -m uvicorn casa_agent.web.app:app --port "$PORT"
