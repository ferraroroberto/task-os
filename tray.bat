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
REM  fleet-config's install.ps1 junction, shelled to as one script run, NOT in
REM  cmd-side `for /f` output capture of PowerShell or inline logic in a
REM  `powershell -Command "..."` string.
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
REM  the reclaim list -- reclaiming one would kill the sibling.
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
REM
REM  The helper is started through this repo's src\ps_script.py (vendored from
REM  the scaffold): under AllSigned / Restricted, where `-File` refuses an
REM  unsigned script, it loads the helper as a ScriptBlock; the machine's
REM  execution policy is never set or overridden. It prints which launch it
REM  used, and a helper it cannot run exits non-zero.
REM ============================================================================

setlocal EnableDelayedExpansion
REM  Clear an APP_NAME the caller already carries: the usual restart route is an
REM  agent in a session that inherited the old leaked value (app-launcher#963).
set "APP_NAME="
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
REM  Namespaced, never a bare APP_NAME: setlocal hides a variable from the
REM  calling console but NOT from children, so the whole tray -> service chain
REM  inherits it, and so does every session and app it spawns -- where APP_NAME
REM  is another project's own config key (app-launcher#963).
set "TRAY_APP_NAME=task-os"
REM === ADAPT (2/4): the args python is started with to launch the tray,
REM     e.g. "scripts\launcher.py tray"  or  "-m tray" ===
set "TRAY_LAUNCH=scripts\launcher.py tray"

set "WANT_RESTART="
if /i "%~1"=="--restart" set "WANT_RESTART=1"
if /i "%~1"=="-r"        set "WANT_RESTART=1"

REM === ADAPT (3/4): a regex matching THIS app's tray invocation. Keep it that
REM     specific: a bare word such as `tray` also matches the script launcher.
set "TRAY_MATCH=(scripts[\\/]+)?launcher\.py\s+tray"
set "PS=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
set "TRAY_VENV=%SCRIPT_DIR%.venv"
REM  ONE shared, machine-local copy owned by fleet-config (project-scaffolding#153)
REM  -- junctioned by fleet-config's install.ps1, never vendored per-app.
set "TRAY_PS=%USERPROFILE%/.claude/tray/tray_lifecycle.ps1"
REM  --restart without the helper stays a hard error: the orphan-proof restart
REM  is fleet-config's job, and degrading it to a plain start would adopt the
REM  stale build, see project-scaffolding#54. A plain start has no such risk, so
REM  it jumps to the standalone start at the bottom. Two flat ifs, not a nested
REM  block: an `exit /b 1` nested inside a block that also holds a `goto` comes
REM  back as exit code 0 under cmd.exe (project-scaffolding#345).
if not exist "%TRAY_PS%" if not defined WANT_RESTART goto :standalone_start
if not exist "%TRAY_PS%" (
    echo ERROR: missing shared tray helper "%TRAY_PS%"
    echo        --restart needs it: install fleet-config and run its install.ps1, then retry.
    echo        See ferraroroberto/fleet-config's README for details.
    exit /b 1
)

REM === ADAPT (4/4): this tray's exclusively-owned port. It is read from the
REM     ignored config/config.json (`port`, else the sample's) by `scripts\launcher.py port`
REM     by the lines below, never a literal here: a second checkout
REM     on another port (a worktree, a second install) must reclaim its own port,
REM     not the live one. Exclude any mutex-shared port. ===
REM Optional override for the restart-verification probe. Leave blank and the
REM helper probes https:// then http:// on 127.0.0.1:<first-owned-port>/api/version
REM (HTTPS first because fleet PWAs are HTTPS; loopback so an auth-gated endpoint
REM takes its bypass and a public-name leaf's cert is skipped - #147). Set this
REM only for a non-standard path, e.g. http://127.0.0.1:8000/admin/api/version.
set "VERSION_URL="

REM  The ports are read from the config, so the helper gets this checkout's own.
REM  An empty or unexpected answer stops here rather than reclaiming nothing. A
REM  checkout with no .venv cannot read them, and could not start the tray
REM  either, so there is no plain -File launch here.
if not exist "%TRAY_VENV%\Scripts\python.exe" echo ERROR: missing "%TRAY_VENV%\Scripts\python.exe" - create this app's .venv first.
if not exist "%TRAY_VENV%\Scripts\python.exe" exit /b 1
set "OWNED_PORTS="
for /f "usebackq delims=" %%p in (`"%TRAY_VENV%\Scripts\python.exe" scripts\launcher.py port`) do set "OWNED_PORTS=%%p"
for /f "delims=0123456789" %%x in ("%OWNED_PORTS%") do set "OWNED_PORTS="
if not defined OWNED_PORTS echo ERROR: could not read the owned ports from the config - launcher.py port
if not defined OWNED_PORTS exit /b 1

REM  The helper's arguments travel as environment variables, never on the
REM  launcher's command line: the helper finds a running tray by matching the
REM  command lines of python.exe processes under this .venv, and would take a
REM  launcher carrying TRAY_LAUNCH for the tray itself. The switch is cleared
REM  first so a value inherited from the caller can never ask for a restart.
set "PSL_ARG_AppName=%TRAY_APP_NAME%"
set "PSL_ARG_ScriptDir=%SCRIPT_DIR_ARG%"
set "PSL_ARG_VenvDir=%TRAY_VENV%"
set "PSL_ARG_TrayMatch=%TRAY_MATCH%"
set "PSL_ARG_Ports=%OWNED_PORTS%"
set "PSL_ARG_TrayLaunch=%TRAY_LAUNCH%"
set "PSL_ARG_VersionUrl=%VERSION_URL%"
set "PSL_SWITCH_Restart="
if defined WANT_RESTART set "PSL_SWITCH_Restart=1"
"%TRAY_VENV%\Scripts\python.exe" -m src.ps_script "%TRAY_PS%" launch
exit /b %ERRORLEVEL%

REM  Standalone start (project-scaffolding#345): the shared helper is missing,
REM  e.g. this app was moved to a PC that has none of the other fleet repos, and
REM  a plain start was asked for. Launch the tray straight from this repo's .venv
REM  and exit 0. No detect/adopt here: the tray's own single-instance guard
REM  (app/tray/single_instance.py) stops a duplicate, and --restart is refused
REM  above, so nothing in this path can mask a stale build.
:standalone_start
set "TRAY_PYW=%TRAY_VENV%\Scripts\pythonw.exe"
if not exist "%TRAY_PYW%" (
    echo ERROR: missing "%TRAY_PYW%" - create this app's .venv first.
    exit /b 1
)
echo NOTE: shared tray helper not found, starting the %TRAY_APP_NAME% tray standalone - --restart needs fleet-config.
REM  Start-Process (as the shared helper does), not cmd `start`: `start` lets the
REM  tray inherit this script's stdout pipe, so a caller capturing our output (an
REM  agent shell, a finisher skill) would block until the tray exits. Values go
REM  through the environment, so no quoting nests inside the -Command string.
%PS% -NoProfile -NonInteractive -Command "Start-Process -FilePath $env:TRAY_PYW -ArgumentList $env:TRAY_LAUNCH -WorkingDirectory $env:SCRIPT_DIR_ARG -WindowStyle Hidden -ErrorAction Stop"
exit /b %ERRORLEVEL%
