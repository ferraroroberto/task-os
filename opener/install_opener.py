#!/usr/bin/env python3
"""Install / remove the task-os folder opener on this PC (Windows, per user).

The same steps ``install.txt``'s one-liner does, through ``winreg`` — for a PC
that has Python (the server itself, a dev box):

    1. copy ``opener.cmd`` + ``opener.ps1`` (next to this script) to
       ``%LOCALAPPDATA%\\task-os\\``
    2. create ``opener.env`` there when missing (placeholder lines, ``name=path``)
    3. register ``HKCU\\Software\\Classes\\taskos`` — ``URL Protocol``, ``DefaultIcon``,
       ``shell\\open\\command``

**Which command gets registered is decided by a probe, not assumed.** The
preferred shape runs the launcher, which takes the URL as an argument and hands
it to ``opener.cmd`` through the environment::

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<dest>\\opener.ps1" -Url "%1"

Registering ``opener.cmd`` directly instead makes Windows hand the URL to a
command interpreter as a *string*, which re-parses it: a quote in the URL ends
the argument and starts a second command (task-os#40 — measured on Windows 11
against every cmd registration shape, all of them injectable). So that shape is
the **fallback**, used only where a machine policy blocks running a script file,
and when it is used the installer says so out loud — a degraded install is a
visible state, never a silent one.

No admin: everything lives under the current user. ``--dry-run`` prints the plan
and touches nothing; ``--uninstall`` removes the key and both handler files (the
``opener.env`` you may have edited stays). Stdlib only.

    python opener\\install_opener.py --dry-run
    python opener\\install_opener.py
    python opener\\install_opener.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HANDLER_NAME = "opener.cmd"
LAUNCHER_NAME = "opener.ps1"
ENV_NAME = "opener.env"
SCHEME = "taskos"
SELFTEST_URL = "taskos://selftest"
SELFTEST_OK = "TASKOS_OPENER_PS_OK"


def key_path(scheme: str = SCHEME) -> str:
    return rf"Software\Classes\{scheme}"
ENV_TEMPLATE = (
    "# task-os opener placeholders — one name=path line per placeholder, no quotes.\n"
    "#   docs=C:\\Users\\me\\Tenant\\docs - Documents     → {sharepoint:docs} and {docs}\n"
    "#   onedrive=D:\\OneDrive                            → overrides {onedrive} (else %OneDriveCommercial% / %OneDrive%)\n"
    "# A value may use %VARS%, e.g. docs=%USERPROFILE%\\Tenant\\docs - Documents\n"
)


def default_dest() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "task-os"


def launcher_command_line(dest: Path) -> str:
    """The preferred registration: an executable that takes the URL as an argument.

    Wrapped in ``conhost.exe --headless`` so ShellExecute allocates no visible
    console — measured on this PC (task-os#130): plain ``powershell.exe``, even
    with ``-WindowStyle Hidden``, still flashes a Windows Terminal window
    because WT is the default terminal here; the headless pseudo-console does
    not. The undocumented switch also swallows stdout on the *caller* side, so
    :func:`launcher_runs` deliberately keeps probing the bare ``powershell.exe
    -File`` form below, unwrapped — the probe only needs to know whether the
    script *runs*, not whether ShellExecute would hide its console.
    """
    return (
        'conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File '
        f'"{dest / LAUNCHER_NAME}" -Url "%1"'
    )


def fallback_command_line(dest: Path) -> str:
    """Used only where the launcher cannot run — see the module docstring."""
    return f'cmd.exe /c ""{dest / HANDLER_NAME}" "%1""'


def command_line(dest: Path, *, launcher: bool) -> str:
    return launcher_command_line(dest) if launcher else fallback_command_line(dest)


def launcher_runs(launcher: Path) -> bool:
    """Can this PC run the launcher? Ask it, don't assume.

    A machine policy can block script files outright, in which case
    ``-ExecutionPolicy Bypass`` does not help and the fallback registration is
    the only one that works. ``opener.ps1 -Url taskos://selftest`` prints a
    token and exits, so the probe runs the exact file that would be registered.
    """
    if sys.platform != "win32" or not launcher.exists():
        return False
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(launcher), "-Url", SELFTEST_URL],
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"note: launcher probe could not run ({exc})", file=sys.stderr)
        return False
    return SELFTEST_OK in proc.stdout.decode("utf-8", "replace")


def plan(dest: Path, *, uninstall: bool, launcher: bool, scheme: str = SCHEME) -> list[str]:
    """Human-readable steps — what --dry-run prints and the real run follows."""
    key = rf"HKCU\{key_path(scheme)}"
    if uninstall:
        return [
            f"delete registry key {key} (recursive)",
            f"delete {dest / HANDLER_NAME}",
            f"delete {dest / LAUNCHER_NAME}",
            f"keep   {dest / ENV_NAME} (your placeholders)",
        ]
    return [
        f"mkdir  {dest}",
        f"copy   {HERE / HANDLER_NAME} -> {dest / HANDLER_NAME}",
        f"copy   {HERE / LAUNCHER_NAME} -> {dest / LAUNCHER_NAME}",
        f"create {dest / ENV_NAME} (only when missing)",
        f"set    {key} (default) = 'URL:task-os opener' · 'URL Protocol' = ''",
        f"set    {key}\\DefaultIcon (default) = 'explorer.exe,0'",
        f"set    {key}\\shell\\open\\command (default) = {command_line(dest, launcher=launcher)}",
        "mode   " + ("launcher (the URL reaches the handler as an argument)"
                     if launcher else
                     "FALLBACK — this PC cannot run the launcher, so the URL reaches a "
                     "command interpreter as a string (see opener/README.md)"),
    ]


def install(dest: Path, scheme: str = SCHEME) -> bool:
    """Copy the handler pair, register the scheme. Returns ``True`` when the
    preferred (launcher) shape was registered, ``False`` for the fallback."""
    import winreg  # Windows only — imported here so --dry-run works anywhere

    for name in (HANDLER_NAME, LAUNCHER_NAME):
        if not (HERE / name).exists():
            raise SystemExit(f"error: {HERE / name} not found (run from the repo's opener/ folder)")
    dest.mkdir(parents=True, exist_ok=True)
    for name in (HANDLER_NAME, LAUNCHER_NAME):
        shutil.copyfile(HERE / name, dest / name)
    env_file = dest / ENV_NAME
    if not env_file.exists():
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")
    launcher = launcher_runs(dest / LAUNCHER_NAME)
    key = key_path(scheme)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:task-os opener")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\DefaultIcon") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "explorer.exe,0")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command_line(dest, launcher=launcher))
    return launcher


def _delete_tree(root: int, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            names = []
            while True:
                try:
                    names.append(winreg.EnumKey(k, len(names)))
                except OSError:
                    break
        for name in names:
            _delete_tree(root, path + "\\" + name)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        return


def uninstall(dest: Path, scheme: str = SCHEME) -> None:
    import winreg

    _delete_tree(winreg.HKEY_CURRENT_USER, key_path(scheme))
    for name in (HANDLER_NAME, LAUNCHER_NAME):
        try:
            (dest / name).unlink()
        except FileNotFoundError:
            pass


def is_installed(dest: Path, scheme: str = SCHEME) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path(scheme) + r"\shell\open\command") as k:
            value, _ = winreg.QueryValueEx(k, None)
    except OSError:
        return False
    registered = str(value).lower()
    # either shape counts as installed — which one it is, is the *mode*, not the fact
    return ((LAUNCHER_NAME in registered and (dest / LAUNCHER_NAME).exists())
            or (HANDLER_NAME in registered and (dest / HANDLER_NAME).exists()))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="install the task-os folder opener for this user")
    p.add_argument("--dest", type=Path, default=default_dest(), help="handler folder (default: %%LOCALAPPDATA%%\\task-os)")
    p.add_argument("--scheme", default=SCHEME, help=f"URL scheme to register (default: {SCHEME}); the tests use a throwaway one")
    p.add_argument("--uninstall", action="store_true", help="remove the URL scheme and the handler files")
    p.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    args = p.parse_args(argv)
    dest = args.dest.expanduser()
    # dry run has nothing copied yet, so probe the repo's own copy — same file
    launcher = args.uninstall or launcher_runs(HERE / LAUNCHER_NAME)
    steps = plan(dest, uninstall=args.uninstall, launcher=launcher, scheme=args.scheme)
    print(("uninstall" if args.uninstall else "install") + " plan" + (" (dry run)" if args.dry_run else "") + ":")
    for step in steps:
        print("  " + step)
    if args.dry_run:
        return 0
    if sys.platform != "win32":
        print("error: the opener registers a Windows URL scheme — nothing to do on this OS", file=sys.stderr)
        return 1
    if args.uninstall:
        uninstall(dest, args.scheme)
        print(f"removed: {args.scheme}:// scheme + {dest / HANDLER_NAME} + {dest / LAUNCHER_NAME}")
    else:
        used_launcher = install(dest, args.scheme)
        print(f"installed: {dest / HANDLER_NAME} — placeholders in {dest / ENV_NAME}")
        if used_launcher:
            print(f"mode:      launcher ({dest / LAUNCHER_NAME})")
        else:
            print("mode:      FALLBACK — this PC cannot run the launcher, so the URL reaches a")
            print("           command interpreter as a string; see opener/README.md 'Caveats'.")
        print(f"try it:    start {args.scheme}://open?ref=%7Bonedrive%7D")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
