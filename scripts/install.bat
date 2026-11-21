@echo off
REM ============================================================================
REM  scripts\install.bat - one install for a fresh PC, and a safe re-run on a used one.
REM ----------------------------------------------------------------------------
REM    scripts\install.bat      create .venv when missing, then python -m src.install
REM    scripts\install.bat -WhatIf   list every change, make none
REM    scripts\install.bat --startup also start the tray at sign-in
REM
REM  Nothing this PC already has is overwritten: an existing .venv is kept, a
REM  config only gains the keys it lacks (after a backup), and a registration
REM  that exists is kept. A second run reports unchanged. Steps and the
REM  checklist: docs/install.md.
REM
REM  A .bat, not a .ps1: cmd.exe runs it under any PowerShell execution policy,
REM  AllSigned included, with nothing to sign. Keep this file ASCII-only (cmd
REM  reads it in the console codepage).
REM ============================================================================

setlocal
REM  It lives in scripts\ and works from the repo root, its parent folder.
cd /d "%~dp0.." || exit /b 1
set "PYTHONUTF8=1"

set "WHATIF="
for %%A in (%*) do if /i "%%~A"=="-WhatIf" set "WHATIF=1"
for %%A in (%*) do if /i "%%~A"=="--whatif" set "WHATIF=1"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto :have_venv
if defined WHATIF goto :whatif_no_venv

call :find_python
if not defined BASE_PY goto :no_python
%BASE_PY% -m venv .venv
if errorlevel 1 (
    echo   [failed] .venv - %BASE_PY% -m venv .venv did not succeed
    exit /b 1
)
echo   [created] .venv - with %BASE_PY%
"%VENV_PY%" -m src.install %*
exit /b %ERRORLEVEL%

:have_venv
echo   [kept] .venv
"%VENV_PY%" -m src.install %*
exit /b %ERRORLEVEL%

REM  -WhatIf on a PC with no .venv yet: the rest of the install only reads the
REM  standard library, so a system Python can list it without creating anything.
:whatif_no_venv
echo   [would-create] .venv - py -3.14 -m venv .venv
call :find_python
if not defined BASE_PY goto :no_python
%BASE_PY% -m src.install %*
exit /b %ERRORLEVEL%

:no_python
echo ERROR: Python 3.14 not found. Install it from python.org (with the py launcher), then re-run scripts\install.bat.
exit /b 1

REM  The stack is fixed at Python 3.14: the py launcher first, then a python on PATH.
:find_python
set "BASE_PY="
py -3.14 -c "import sys" >nul 2>nul && set "BASE_PY=py -3.14"
if defined BASE_PY exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)" >nul 2>nul && set "BASE_PY=python"
exit /b 0
