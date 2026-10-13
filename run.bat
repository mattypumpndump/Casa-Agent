@echo off
REM One-command start for Windows: creates venv, installs deps, writes .env, starts server, opens browser.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3 is not installed. Get it from https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m playwright install chromium >nul 2>nul
if not exist .env (copy .env.example .env >nul & echo Created .env - add your ANTHROPIC_API_KEY there later.)
echo Starting Casa Agent at http://127.0.0.1:8000  (Ctrl+C to stop)
start "" http://127.0.0.1:8000
python -m uvicorn casa_agent.web.app:app --port 8000
