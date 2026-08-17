@echo off
chcp 65001 >nul
REM ============================================================================
REM  WEBAPP - standalone FastAPI dev launcher for task-os (:8448)
REM ----------------------------------------------------------------------------
REM  Daily use: launch tray.bat instead -- it adopt-or-spawns the webapp for
REM  you and self-heals it. This bat is for headless boxes and dev iteration.
REM  HTTPS when webapp\certificates\{cert,key}.pem exist (Tailscale cert from
REM  scripts\gen_tailscale_cert.py; --check below auto-renews a leaf expiring
REM  within ~30 days before uvicorn binds), plain HTTP otherwise -- said loudly.
REM  Same decision as app\webapp\manager.py under the tray; keep them agreeing.
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

REM Auto-renew a Tailscale leaf expiring soon (never blocks; no-op without a cert).
"%VENV_PY%" "%SCRIPT_DIR%scripts\gen_tailscale_cert.py" --check

set "SSL_ARGS="
if exist "%SCRIPT_DIR%webapp\certificates\cert.pem" if exist "%SCRIPT_DIR%webapp\certificates\key.pem" (
    set "SSL_ARGS=--ssl-keyfile webapp\certificates\key.pem --ssl-certfile webapp\certificates\cert.pem"
)
if defined SSL_ARGS (
    echo [INFO] task-os webapp on https://127.0.0.1:8448 ^(Tailscale cert; use the .ts.net name from other devices^)
) else (
    echo [WARN] no webapp\certificates\{cert,key}.pem -- serving PLAIN HTTP on http://127.0.0.1:8448
    echo [WARN] run: .venv\Scripts\python.exe scripts\gen_tailscale_cert.py
)
"%VENV_PY%" -m uvicorn app.webapp.server:app --host 0.0.0.0 --port 8448 --loop "%LOOP_ARG%" %SSL_ARGS%
exit /b %ERRORLEVEL%
