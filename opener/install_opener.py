#!/usr/bin/env python3
"""Install / remove the task-os folder opener on this PC (Windows, per user).

The same three steps ``install.txt``'s one-liner does, through ``winreg`` — for
a PC that has Python (the server itself, a dev box):

    1. copy ``opener.cmd`` (next to this script) to ``%LOCALAPPDATA%\\task-os\\``
    2. create ``opener.env`` there when missing (placeholder lines, ``name=path``)
    3. register ``HKCU\\Software\\Classes\\taskos`` — ``URL Protocol``, ``DefaultIcon``,
       ``shell\\open\\command`` = ``cmd.exe /c ""<dest>\\opener.cmd" "%1""``

No admin: everything lives under the current user. ``--dry-run`` prints the plan
and touches nothing; ``--uninstall`` removes the key and ``opener.cmd`` (the
``opener.env`` you may have edited stays). Stdlib only.

    python opener\\install_opener.py --dry-run
    python opener\\install_opener.py
    python opener\\install_opener.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HANDLER_NAME = "opener.cmd"
ENV_NAME = "opener.env"
SCHEME = "taskos"
KEY_PATH = rf"Software\Classes\{SCHEME}"
ENV_TEMPLATE = (
    "# task-os opener placeholders — one name=path line per placeholder, no quotes.\n"
    "#   docs=C:\\Users\\me\\Tenant\\docs - Documents     → {sharepoint:docs} and {docs}\n"
    "#   onedrive=D:\\OneDrive                            → overrides {onedrive} (else %OneDriveCommercial% / %OneDrive%)\n"
    "# A value may use %VARS%, e.g. docs=%USERPROFILE%\\Tenant\\docs - Documents\n"
)


def default_dest() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "task-os"


def command_line(dest: Path) -> str:
    return f'cmd.exe /c ""{dest / HANDLER_NAME}" "%1""'


def plan(dest: Path, *, uninstall: bool) -> list[str]:
    """Human-readable steps — what --dry-run prints and the real run follows."""
    key = rf"HKCU\{KEY_PATH}"
    if uninstall:
        return [
            f"delete registry key {key} (recursive)",
            f"delete {dest / HANDLER_NAME}",
            f"keep   {dest / ENV_NAME} (your placeholders)",
        ]
    return [
        f"mkdir  {dest}",
        f"copy   {HERE / HANDLER_NAME} -> {dest / HANDLER_NAME}",
        f"create {dest / ENV_NAME} (only when missing)",
        f"set    {key} (default) = 'URL:task-os opener' · 'URL Protocol' = ''",
        f"set    {key}\\DefaultIcon (default) = 'explorer.exe,0'",
        f"set    {key}\\shell\\open\\command (default) = {command_line(dest)}",
    ]


def install(dest: Path) -> None:
    import winreg  # Windows only — imported here so --dry-run works anywhere

    src = HERE / HANDLER_NAME
    if not src.exists():
        raise SystemExit(f"error: {src} not found (run from the repo's opener/ folder)")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest / HANDLER_NAME)
    env_file = dest / ENV_NAME
    if not env_file.exists():
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:task-os opener")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH + r"\DefaultIcon") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "explorer.exe,0")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH + r"\shell\open\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, command_line(dest))


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


def uninstall(dest: Path) -> None:
    import winreg

    _delete_tree(winreg.HKEY_CURRENT_USER, KEY_PATH)
    try:
        (dest / HANDLER_NAME).unlink()
    except FileNotFoundError:
        pass


def is_installed(dest: Path) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH + r"\shell\open\command") as k:
            value, _ = winreg.QueryValueEx(k, None)
    except OSError:
        return False
    return str(value).lower().find(HANDLER_NAME) >= 0 and (dest / HANDLER_NAME).exists()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="install the task-os folder opener for this user")
    p.add_argument("--dest", type=Path, default=default_dest(), help="handler folder (default: %%LOCALAPPDATA%%\\task-os)")
    p.add_argument("--uninstall", action="store_true", help="remove the URL scheme and opener.cmd")
    p.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    args = p.parse_args(argv)
    dest = args.dest.expanduser()
    steps = plan(dest, uninstall=args.uninstall)
    print(("uninstall" if args.uninstall else "install") + " plan" + (" (dry run)" if args.dry_run else "") + ":")
    for step in steps:
        print("  " + step)
    if args.dry_run:
        return 0
    if sys.platform != "win32":
        print("error: the opener registers a Windows URL scheme — nothing to do on this OS", file=sys.stderr)
        return 1
    if args.uninstall:
        uninstall(dest)
        print(f"removed: {SCHEME}:// scheme + {dest / HANDLER_NAME}")
    else:
        install(dest)
        print(f"installed: {dest / HANDLER_NAME} — placeholders in {dest / ENV_NAME}")
        print(f"try it:    start {SCHEME}://open?ref=%7Bonedrive%7D")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
