"""Start a PowerShell script under any execution policy, without weakening it.

``powershell -File x.ps1`` refuses an unsigned script when the effective execution policy is
``AllSigned`` (or ``Restricted``). Overriding the policy on the command line would weaken the
machine owner's own control, so this launcher never does. A script *loaded as text* and invoked
as a ScriptBlock is not a file execution, so the policy does not apply to it and stays exactly
as the machine set it.

* a policy that lets unsigned local files run (``Bypass`` / ``Unrestricted`` /
  ``RemoteSigned``) -> the plain ``-File`` launch;
* any other policy, or one that could not be read -> the ScriptBlock launch.

The method used is printed to stderr, and the exit code is the script's own: a script that
cannot be read, parsed, bound or run to its end exits non-zero.

CLI, for ``tray.bat`` and other non-Python callers (run from the repo root)::

    python -m src.ps_script <script.ps1> [args...]

Arguments pass through verbatim. A caller whose arguments must not appear on this process's
command line passes them as environment variables instead: ``PSL_ARG_<Name>=<value>`` becomes
``-<Name> <value>`` and a non-empty ``PSL_SWITCH_<Name>`` becomes ``-<Name>``. ``tray.bat``
needs this: the tray helper finds a running tray by matching the command lines of ``python.exe``
processes under the repo's ``.venv``, and a launcher carrying the tray's own launch arguments
would match -- a plain start would report "already running" and a restart would stop itself.
No ``PSL_`` variable reaches the script or anything it starts.

A script run this way must not rely on ``$PSCommandPath`` or
``$MyInvocation.MyCommand.Path`` (empty: there is no file behind a ScriptBlock).
``$PSScriptRoot`` is supplied. A .NET or cmdlet statement-terminating error ends the script
with exit 1, where ``-File`` would print it and carry on.

Vendor-verbatim: copy this file byte-identical into ``src/`` (manifest key ``ps_script``).
Self-contained on purpose, standard library only, Python 3.9.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

_log = logging.getLogger("ps_script")

POWERSHELL_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

# Policies under which an unsigned local script may be started with -File.
FILE_LAUNCH_POLICIES = frozenset({"bypass", "unrestricted", "remotesigned"})

# A console-less caller (an agent's captured shell, a scheduled task) would otherwise get a
# fresh console window per child. Derived here, not imported: this file is vendored verbatim.
_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Bound on the one `Get-ExecutionPolicy` probe (a PowerShell cold start).
_PROBE_TIMEOUT_S = 30.0

_PREFIX = "PSL_"
_ARG_PREFIX = "PSL_ARG_"
_SWITCH_PREFIX = "PSL_SWITCH_"
ENV_SCRIPT = "PSL_SCRIPT"
ENV_ARGV = "PSL_ARGV"
# Each argument rides in ENV_ARGV behind one unit-separator character, so an empty argument and
# a value holding spaces both survive (a -Command string would re-parse them, and Windows
# PowerShell 5.1 hands a parsed JSON array back as one object).
_ARG_SEP = chr(31)

# One line, single quotes only: it travels as one argv element, and a double quote or a
# backslash before one would be re-escaped on the way. Which token is a switch, which takes a
# value and which is positional comes from the script's own param() block, so a value that
# starts with a dash (`-TrayLaunch '-m tray'`) stays a value, as it does under -File. An `exit`
# inside the script ends this process with its code; success is only ever reached by the script
# returning, so a failure anywhere before that exits 1.
BOOTSTRAP = (
    "$PSL_Path = $env:PSL_SCRIPT; "
    "$PSL_Argv = @($env:PSL_ARGV -split [char]31 | Select-Object -Skip 1); "
    "Remove-Item -ErrorAction SilentlyContinue Env:PSL_SCRIPT, Env:PSL_ARGV; "
    "$PSL_Ok = $false; "
    "try { "
    "$PSL_Path = [IO.Path]::GetFullPath($PSL_Path); "
    "$PSL_Root = Split-Path -Parent $PSL_Path; "
    "$PSL_Block = [scriptblock]::Create([IO.File]::ReadAllText($PSL_Path).Replace('$PSScriptRoot', '$PSL_Root')); "
    "$PSL_Params = @($PSL_Block.Ast.ParamBlock.Parameters | Where-Object { $_ }); "
    "function Find-PslParam([string] $Token) { "
    "if ($Token -notmatch '^-([A-Za-z_]\\w*)$') { return } "
    "$n = $Matches[1]; "
    "$hit = @($PSL_Params | Where-Object { $_.Name.VariablePath.UserPath -eq $n }); "
    "if (-not $hit) { $hit = @($PSL_Params | Where-Object { $_.Name.VariablePath.UserPath -like ($n + '*') }) } "
    "if ($hit.Count -eq 1) { $hit[0] } "
    "} "
    "$PSL_Pos = @(); $PSL_Named = @{}; "
    "for ($i = 0; $i -lt $PSL_Argv.Count; $i++) { "
    "$t = [string]$PSL_Argv[$i]; "
    "if ($t -notmatch '^-[A-Za-z_]\\w*$') { $PSL_Pos += $t; continue } "
    "$p = Find-PslParam $t; $name = $t.Substring(1); "
    "if ($p -and $p.StaticType -eq [switch]) { $PSL_Named[$name] = $true; continue } "
    "$more = ($i + 1 -lt $PSL_Argv.Count) -and -not (Find-PslParam $PSL_Argv[$i + 1]); "
    "if ($more) { $PSL_Named[$name] = $PSL_Argv[$i + 1]; $i++ } "
    "elseif ($p) { throw ('Missing an argument for parameter ' + $name) } "
    "else { $PSL_Named[$name] = $true } "
    "} "
    "& $PSL_Block @PSL_Pos @PSL_Named; "
    "$PSL_Ok = $true "
    "} catch { [Console]::Error.WriteLine(($_ | Out-String)) }; "
    "if (-not $PSL_Ok) { exit 1 }; "
    "exit 0"
)


def effective_policy(timeout: float = _PROBE_TIMEOUT_S) -> str | None:
    """The effective execution policy, lower-cased, or ``None`` when not confirmed."""
    # A PowerShell 7 parent hands down a PSModulePath that Windows PowerShell 5.1 cannot load
    # Microsoft.PowerShell.Security from, so the probe would fail for want of its own module.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    try:
        done = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-Command", "Get-ExecutionPolicy"],
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("execution policy not confirmed (%s)", exc)
        return None
    value = done.stdout.strip().lower()
    if done.returncode != 0 or not value:
        _log.warning(
            "execution policy not confirmed (exit %s: %s)", done.returncode, done.stderr.strip()[:200]
        )
        return None
    return value


def script_command(
    script: str | Path, args: Sequence[str] = (), *, policy: str | None
) -> tuple[list[str], dict[str, str]]:
    """The argv, plus the extra environment, that starts ``script`` under ``policy``.

    ``policy`` is the effective policy from :func:`effective_policy`; ``None``
    (not confirmed) takes the ScriptBlock launch, which works under all of them.
    """
    base = [POWERSHELL_EXE, "-NoProfile", "-NonInteractive"]
    if policy in FILE_LAUNCH_POLICIES:
        return base + ["-File", str(script), *args], {}
    return (
        base + ["-Command", BOOTSTRAP],
        {ENV_SCRIPT: str(script), ENV_ARGV: "".join(_ARG_SEP + a for a in args)},
    )


def env_args(environ: Mapping[str, str]) -> list[str]:
    """The script arguments carried by ``PSL_ARG_*`` / ``PSL_SWITCH_*`` variables.

    Windows variable names are case-insensitive and arrive upper-cased, which PowerShell
    parameter binding does not care about.
    """
    args: list[str] = []
    for key in sorted(environ):
        upper, value = key.upper(), environ[key]
        if upper.startswith(_ARG_PREFIX):
            args += ["-" + key[len(_ARG_PREFIX):], value]
        elif upper.startswith(_SWITCH_PREFIX) and value:
            args.append("-" + key[len(_SWITCH_PREFIX):])
    return args


def _child_flags() -> int:
    """No window of its own only when there is no console here to share.

    A child given its own hidden console writes there even when handed this console's handles,
    so a person running tray.bat in a terminal would see none of the script's output. With a
    console attached the child shares it and no window can appear.
    """
    if sys.platform == "win32" and ctypes.windll.kernel32.GetConsoleCP():
        return 0
    return _NO_WINDOW


def _std_handle(stream: object) -> int:
    """The caller's own std handle for the child, or DEVNULL when it has none.

    A child with no window gets a console of its own, so a handle left to default would be
    that hidden console and the script's output would never reach the caller.
    """
    try:
        return int(stream.fileno())  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return subprocess.DEVNULL


def run_script(script: str | Path, args: Sequence[str] = (), *, timeout: float | None) -> int:
    """Run ``script`` to completion on the caller's std streams and return its exit code."""
    policy = effective_policy()
    argv, extra = script_command(script, args, policy=policy)
    method = "ScriptBlock" if extra else "-File"
    _log.info(
        "PowerShell launch: %s for %s (execution policy %s, unchanged)",
        method,
        Path(script).name,
        policy or "not confirmed",
    )
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_PREFIX)}
    try:
        done = subprocess.run(
            argv,
            env={**env, **extra},
            stdout=_std_handle(sys.stdout),
            stderr=_std_handle(sys.stderr),
            timeout=timeout,
            check=False,
            creationflags=_child_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log.error("could not run %s (%s)", Path(script).name, exc)
        return 1
    return done.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m src.ps_script <script> [args...]``."""
    items = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    if not items:
        _log.error("usage: python -m src.ps_script <script.ps1> [args...]")
        return 2
    script, args = items[0], items[1:]
    if not Path(script).is_file():
        _log.error("missing PowerShell script: %s", script)
        return 1
    # No timeout: the script's lifetime is the caller's to bound.
    return run_script(script, args + env_args(os.environ), timeout=None)


if __name__ == "__main__":
    raise SystemExit(main())
