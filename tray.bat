@echo off
chcp 65001 >nul
REM ============================================================================
REM  task-os TRAY - tray icon that owns a long-lived service lifecycle
REM ----------------------------------------------------------------------------
REM  CANONICAL TEMPLATE. Copy to `tray.bat` in a tray-resident app, then replace
REM  the four __PLACEHOLDER__ tokens (marked `=== ADAPT ===`). Everything else is
REM  the orphan-proof reclaim-then-start machinery and is copied verbatim, so a
REM  filled-in copy is byte-identical to every sister tray. Full reasoning:
REM  scaffold docs/windows-tray.md + project-scaffolding#29.
REM
REM  Launch this on login (Startup folder) for an always-on service.
REM
REM  Idempotent:
REM    tray.bat              -> no-op if a task-os tray is already running
REM    tray.bat --restart    -> stop the running tray (and its service tree) and
REM                             start a fresh one
REM
REM  Detection matches the tray process by command line + this project's .venv
REM  path via CIM, then kills BY PID with /T. We never blanket-kill pythonw, so
REM  sister-app trays and any other python processes are untouched.
REM
REM  The full detect -> kill -> reclaim -> start -> verify lifecycle lives in
REM  the ONE shared, machine-local tray_lifecycle.ps1 owned by fleet-config
REM  (project-scaffolding#153) -- exposed at %USERPROFILE%\.claude\tray\ by
REM  fleet-config's install.ps1 junction, shelled to with -File, NOT in
REM  cmd-side `for /f` output capture or inline `powershell -Command "..."`.
REM  Both cmd shapes have failed under non-interactive nested callers (Git Bash
REM  -> `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool): detect
REM  output came back empty, nothing was killed, and --restart silently degraded
REM  to a plain start that adopted the stale webapp and reported success.
REM  Delegating once to PowerShell makes behavior identical from any caller and
REM  lets stale git_sha verification fail loudly (project-scaffolding#54).
REM
REM  --restart is orphan-proof: besides killing the tray subtree, it reclaims
REM  this app's owned service ports by their owning PID, regardless of process
REM  parentage. A service child that got detached from its tray (a stale process
REM  from an earlier run) would otherwise survive a subtree kill, block the fresh
REM  tray from binding, and keep serving the old build while the restart reports
REM  success. The reclaim is scoped to processes whose CommandLine is under THIS
REM  repo's .venv (NOT the process image path): a venv-launched pythonw re-execs
REM  the base interpreter, so .Path reports the shared base python while only the
REM  CommandLine still carries the .venv path. Matching the image path would miss
REM  the real service; the CommandLine scope keeps the sweep on THIS repo only.
REM
REM  Mutex-shared ports (a port another app may legitimately own) must NOT go in
REM  the 8448 reclaim list -- reclaiming one would kill the sibling.
REM
REM  Keep this whole file ASCII-only. cmd.exe read-ahead-buffers a chunk of the
REM  batch file for parsing at the codepage active when the buffer was filled;
REM  `chcp 65001` above switches the codepage mid-file, so a multi-byte UTF-8
REM  character anywhere in that pre-fetched window gets misparsed and throws
REM  spurious `'X' is not recognized as an internal or external command` errors
REM  on unrelated later lines (project-scaffolding#183). Write prose docs with
REM  em-dashes elsewhere; keep this file plain ASCII, same rule as the shared
REM  tray_lifecycle.ps1 (docs/windows-tray.md, "Platform gotcha") for a
REM  different underlying reason (PS 5.1 parsing, not cmd.exe read-ahead).
REM ============================================================================

setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
REM  `%~dp0` always ends in a trailing backslash, which is what the path joins
REM  below want -- but NOT what a quoted argument can carry. Windows argv parsing
REM  treats an odd run of backslashes before a closing quote as escaping that
REM  quote, so `-ScriptDir "%SCRIPT_DIR%"` swallows the rest of the command line
REM  and every later switch (-TrayMatch, -Ports, ...) arrives EMPTY -- detect
REM  matches nothing, reclaim reclaims nothing, and --restart silently degrades
REM  to the adopt-the-stale-build start this template exists to prevent
REM  (project-scaffolding#145). Pass the de-slashed copy as the argument.
set "SCRIPT_DIR_ARG=%SCRIPT_DIR:~0,-1%"

cd /d "%SCRIPT_DIR%" || exit /b 1

REM === ADAPT (1/4): short app name, used in messages + the start window title ===
set "APP_NAME=task-os"
REM === ADAPT (2/4): the args python is started with to launch the tray,
REM     e.g. "launcher.py tray"  or  "-m tray" ===
set "TRAY_LAUNCH=launcher.py tray"

set "WANT_RESTART="
if /i "%~1"=="--restart" set "WANT_RESTART=1"
if /i "%~1"=="-r"        set "WANT_RESTART=1"

REM === ADAPT (3/4): the -TrayMatch below is a regex matching THIS app's tray
REM     invocation (launcher\.py\s+tray) -- filled in from the template.
set "PS=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
set "TRAY_VENV=%SCRIPT_DIR%.venv"
REM  ONE shared, machine-local copy owned by fleet-config (project-scaffolding#153)
REM  -- junctioned by fleet-config's install.ps1, never vendored per-app.
set "TRAY_PS=%USERPROFILE%/.claude/tray/tray_lifecycle.ps1"
if not exist "%TRAY_PS%" (
    echo ERROR: missing shared tray helper "%TRAY_PS%"
    echo        Fix: install fleet-config and run its install.ps1, then retry.
    echo        See ferraroroberto/fleet-config's README for details.
    exit /b 1
)

REM === ADAPT (4/4): replace 8448 with this tray's exclusively-owned
REM     ports as a comma list, e.g. 8445,8446 . Exclude any mutex-shared port. ===
set "OWNED_PORTS=8448"
REM Optional override for the restart-verification probe. Leave blank and the
REM helper probes https:// then http:// on 127.0.0.1:<first-owned-port>/api/version
REM (HTTPS first because fleet PWAs are HTTPS; loopback so an auth-gated endpoint
REM takes its bypass and a public-name leaf's cert is skipped - #147). Set this
REM only for a non-standard path, e.g. http://127.0.0.1:8000/admin/api/version.
set "VERSION_URL="

set "RESTART_ARG="
if defined WANT_RESTART set "RESTART_ARG=-Restart"

%PS% -NoProfile -NonInteractive -File "%TRAY_PS%" launch -AppName "%APP_NAME%" -ScriptDir "%SCRIPT_DIR_ARG%" -VenvDir "%TRAY_VENV%" -TrayMatch "launcher\.py\s+tray" -Ports "%OWNED_PORTS%" -TrayLaunch "%TRAY_LAUNCH%" -VersionUrl "%VERSION_URL%" !RESTART_ARG!
exit /b %ERRORLEVEL%
