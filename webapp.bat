@echo off
chcp 65001 >nul
REM ============================================================================
REM  WEBAPP - standalone FastAPI dev launcher for task-os (HTTP on :8448)
REM ----------------------------------------------------------------------------
REM  Daily use: launch tray.bat instead -- it adopt-or-spawns the webapp for
REM  you and self-heals it. This bat is for headless boxes and dev iteration.
REM  HTTPS (Tailscale cert) arrives with the phone step; until then plain HTTP.
REM ============================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv missing. Run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

cd /d "%SCRIPT_DIR%" || exit /b 1

REM --loop keeps uvicorn off the default Windows proactor loop, whose accept
REM path dies on a single aborted client connection (app-launcher#388).
REM Keep in sync with app\webapp\event_loop.py:LOOP_FACTORY.
set "LOOP_ARG=app.webapp.event_loop:selector_loop_factory"

echo [INFO] task-os webapp on http://127.0.0.1:8448
"%VENV_PY%" -m uvicorn app.webapp.server:app --host 0.0.0.0 --port 8448 --loop "%LOOP_ARG%"
exit /b %ERRORLEVEL%
