@echo off
chcp 65001 >nul
REM ============================================================================
REM  WEBAPP - standalone FastAPI dev launcher for task-os.
REM ----------------------------------------------------------------------------
REM  Daily use: launch tray.bat instead -- it adopt-or-spawns the webapp for
REM  you and self-heals it. This bat is for headless boxes and dev iteration.
REM
REM  It only finds the venv and hands over to launcher.py, which owns the
REM  port (config.json's `port`, NOT a literal here), the HTTPS decision
REM  (src/certs.py: the Tailscale pair under webapp\certificates\ when it is
REM  there, plain HTTP said loudly otherwise, --check auto-renew before the
REM  bind) and the event loop -- the same code path the tray's manager.py
REM  takes. Two spawn points that share one implementation cannot drift; three
REM  that each re-derive it did (this file used to hardcode :8448, so a repo
REM  checkout on another port -- a worktree, a second install -- silently
REM  fought the running instance for the wrong port).
REM ============================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv missing. Run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

cd /d "%SCRIPT_DIR%" || exit /b 1
"%VENV_PY%" "%SCRIPT_DIR%launcher.py" webapp
exit /b %ERRORLEVEL%
