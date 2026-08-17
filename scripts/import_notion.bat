@echo off
REM import_notion - one-shot, idempotent Notion -> task-os importer (scripts/import_notion.py).
REM   import_notion --dry-run --database-id <id> --env-file <path\.env>   report only, writes nothing
REM   import_notion --database-id <id> --env-file <path\.env>             import into data\tasks.db
REM `import_notion --help` lists every flag (--db, --limit, --json-dump, --from-json).
setlocal
set "PYTHONUTF8=1"
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv missing. Run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt 1>&2
    exit /b 1
)
cd /d "%~dp0.." || exit /b 1
"%VENV_PY%" -m scripts.import_notion %*
exit /b %ERRORLEVEL%
