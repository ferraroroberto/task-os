@echo off
REM import_sharepoint - one-shot, idempotent SharePoint list -> task-os importer (src/imports/sharepoint.py).
REM   import_sharepoint --from-json <dump.json> --mapping config\sharepoint-mapping.json --dry-run   report only
REM   import_sharepoint --from-json <dump.json> --mapping config\sharepoint-mapping.json             import into data\tasks.db
REM `import_sharepoint --help` lists every flag (--db). The guide is docs\sharepoint-import.md.
setlocal
set "PYTHONUTF8=1"
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] .venv missing. Run: py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt 1>&2
    exit /b 1
)
cd /d "%~dp0.." || exit /b 1
"%VENV_PY%" -m src.imports.sharepoint %*
exit /b %ERRORLEVEL%
