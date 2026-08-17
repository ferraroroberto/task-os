@echo off
REM tasks - the task-os CLI (src/cli.py). Talks to the running app on :8448 when
REM it answers, otherwise straight to data/tasks.db. `tasks --help` lists commands.
setlocal
set "PYTHONUTF8=1"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv missing. Run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt 1>&2
    exit /b 1
)
cd /d "%~dp0" || exit /b 1
"%VENV_PY%" -m src.cli %*
exit /b %ERRORLEVEL%
