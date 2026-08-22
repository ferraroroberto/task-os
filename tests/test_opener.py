"""The per-PC folder opener (``opener/``, Step 9), run **for real** through
``cmd.exe`` — the environment points at a temp tree (``OneDrive``,
``OneDriveCommercial``, ``USERNAME``, ``LOCALAPPDATA``) and
``TASKOS_OPENER_DRYRUN=1`` makes the handler print ``open: <path>`` /
``missing: <path>`` instead of launching Explorer. Windows-only (skipped
elsewhere); ``install_opener.py --dry-run`` and ``src/opener.py`` run anywhere."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from src import opener as opener_info
from src.placeholders import opener_url

REPO = Path(__file__).resolve().parents[1]
HANDLER = REPO / "opener" / "opener.cmd"
LAUNCHER = REPO / "opener" / "opener.ps1"
INSTALLER = REPO / "opener" / "install_opener.py"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the opener is a Windows cmd handler")


def _console_encoding() -> str:
    """cmd/PowerShell children print in the inherited console code page (OEM 850
    under a plain console, UTF-8 under a chcp 65001 host) — decode with that."""
    if sys.platform != "win32":
        return "utf-8"
    try:
        import ctypes

        cp = int(ctypes.windll.kernel32.GetConsoleOutputCP())
        return "utf-8" if cp == 65001 else f"cp{cp}"
    except Exception:  # noqa: BLE001 — no console at all (e.g. pythonw): OEM default
        return "cp850"


CONSOLE_ENC = _console_encoding()


@pytest.fixture
def pc(tmp_path: Path) -> dict[str, str]:
    """A fake PC: OneDrive + a second sync root + a %LOCALAPPDATA% with opener.env."""
    od = tmp_path / "od"
    (od / "house" / "kitchen (2024)").mkdir(parents=True)
    (od / "task-os").mkdir()
    (od / "notes.txt").write_text("x", encoding="utf-8")
    sp = tmp_path / "sp" / "docs - Documents" / "plans"
    sp.mkdir(parents=True)
    la = tmp_path / "la"
    (la / "task-os").mkdir(parents=True)
    (la / "task-os" / "opener.env").write_text(
        "# comment line\n"
        f"docs={tmp_path / 'sp' / 'docs - Documents'}\n"
        "viaenv=%TASKOS_TEST_ROOT%\\sp\n",
        encoding="utf-8",
    )
    return {"od": str(od), "sp": str(sp), "la": str(la), "root": str(tmp_path)}


def _pc_env(pc: dict[str, str], dryrun: bool, env_over: dict[str, str]) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items()
            if k not in ("TASKOS_OPENER_ENV", "TASKOS_OPENER_URL")}
    env = {**base, "OneDrive": pc["od"], "OneDriveCommercial": "", "USERNAME": "tester",
           "LOCALAPPDATA": pc["la"], "TASKOS_TEST_ROOT": pc["root"], **env_over}
    if dryrun:
        env["TASKOS_OPENER_DRYRUN"] = "1"
    else:
        env.pop("TASKOS_OPENER_DRYRUN", None)
    return env


def run_opener(url: str, pc: dict[str, str], *, dryrun: bool = True, **env_over: str) -> subprocess.CompletedProcess:
    """The handler on its own — the fallback registration's shape, and a direct call."""
    env = _pc_env(pc, dryrun, env_over)
    # exactly what the fallback registration runs: cmd.exe /c ""<handler>" "<url>""
    cmd = f'cmd.exe /c ""{HANDLER}" "{url}""'
    return subprocess.run(cmd, input=b"\r\n", capture_output=True, env=env, timeout=30)


def run_launcher(url: str, pc: dict[str, str], *, dryrun: bool = True, **env_over: str) -> subprocess.CompletedProcess:
    """The preferred registration: ``powershell.exe -File opener.ps1 -Url "<url>"``.

    ``subprocess`` with an argument **list** is what the shell does to an
    executable's command line — the URL arrives as one argv element, which is
    the whole point of the launcher.
    """
    env = _pc_env(pc, dryrun, env_over)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(LAUNCHER), "-Url", url],
        input=b"\r\n", capture_output=True, env=env, timeout=60,
    )


def _decode(raw: bytes) -> str:
    """cmd echoes in the console code page; the PowerShell fallback writes UTF-8
    when redirected — try UTF-8 first (strict), else the console's page."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(CONSOLE_ENC, errors="replace")


def _out(r: subprocess.CompletedProcess) -> str:
    return _decode(r.stdout).strip()


@windows_only
def test_decodes_and_expands_onedrive_from_the_chip_url(pc: dict[str, str]) -> None:
    r = run_opener(opener_url("{onedrive}/house/kitchen (2024)"), pc)
    assert r.returncode == 0 and _out(r) == f"open: {pc['od']}\\house\\kitchen (2024)"


@windows_only
def test_accepts_the_path_form_and_bare_refs(pc: dict[str, str]) -> None:
    assert _out(run_opener("taskos://open/{onedrive}/task-os", pc)) == f"open: {pc['od']}\\task-os"
    assert _out(run_opener("taskos://open/?ref=%7Bonedrive%7D%2Ftask-os", pc)) == f"open: {pc['od']}\\task-os"
    assert _out(run_opener("taskos://open?ref=%7Bonedrive%7D%2Ftask-os%2F", pc)) == f"open: {pc['od']}\\task-os"


@windows_only
def test_decodes_the_awkward_characters(pc: dict[str, str]) -> None:
    ref = "{onedrive}/x/100% #tag a&b,c+d;e=f@g [h] ~i 'j'"
    r = run_opener(opener_url(ref), pc)
    assert _out(r) == f"missing: {pc['od']}\\x\\100% #tag a&b,c+d;e=f@g [h] ~i 'j'"
    # a percent sequence outside the pure-cmd set (é) → the inline PowerShell fallback,
    # which applies the same placeholder rules (env, opener.env) and the same dry-run contract
    r = run_opener(opener_url("{onedrive}/café"), pc)
    assert _out(r) == f"missing: {pc['od']}\\café"
    assert _out(run_opener(opener_url("{sharepoint:docs}/plans/été"), pc)) == f"missing: {pc['sp']}\\été"
    assert _out(run_opener(opener_url("{onedrive}/x/100% #tag ñ"), pc)) == f"missing: {pc['od']}\\x\\100% #tag ñ"
    r = run_opener(opener_url("{onedrive}/café"), pc, dryrun=False)
    assert r.returncode == 1 and "not synced on this PC" in _decode(r.stdout) and "café" in _decode(r.stdout)
    # backslashes and colons survive an absolute path pasted as the ref
    assert _out(run_opener(opener_url(pc["od"] + "\\task-os"), pc)) == f"open: {pc['od']}\\task-os"


@windows_only
def test_user_and_sharepoint_from_env_file(pc: dict[str, str]) -> None:
    assert _out(run_opener(opener_url("{user}/code"), pc)) == "missing: tester\\code"
    r = run_opener(opener_url("{sharepoint:docs}/plans"), pc)
    assert _out(r) == f"open: {pc['sp']}"
    # a name=path line also serves {name}, and %VARS% inside the value expand
    assert _out(run_opener(opener_url("{docs}/plans"), pc)) == f"open: {pc['sp']}"
    assert _out(run_opener(opener_url("{viaenv}/docs - Documents"), pc)) == f"open: {pc['root']}\\sp\\docs - Documents"


@windows_only
def test_onedrive_commercial_wins_and_env_file_overrides(pc: dict[str, str], tmp_path: Path) -> None:
    r = run_opener(opener_url("{onedrive}/docs - Documents"), pc, OneDriveCommercial=str(tmp_path / "sp"))
    assert _out(r) == f"open: {tmp_path / 'sp'}\\docs - Documents"
    env_file = tmp_path / "custom.env"
    env_file.write_text(f"onedrive={tmp_path / 'sp'}\n", encoding="utf-8")
    r = run_opener(opener_url("{onedrive}/docs - Documents"), pc, TASKOS_OPENER_ENV=str(env_file))
    assert _out(r) == f"open: {tmp_path / 'sp'}\\docs - Documents"


@windows_only
def test_file_ref_and_unknown_placeholder(pc: dict[str, str]) -> None:
    assert _out(run_opener(opener_url("{onedrive}/notes.txt"), pc)) == f"open: {pc['od']}\\notes.txt"
    assert _out(run_opener(opener_url("{nope}/x"), pc)) == "missing: {nope}\\x"


@windows_only
def test_missing_path_shows_the_notice_for_real(pc: dict[str, str]) -> None:
    r = run_opener(opener_url("{onedrive}/not-synced-here"), pc, dryrun=False)
    assert r.returncode == 1
    out = _decode(r.stdout)
    assert "task-os opener" in out and "not synced on this PC" in out
    assert f"{pc['od']}\\not-synced-here" in out
    assert "opener.env" in out and "Press any key" in out


@windows_only
def test_the_launcher_opens_a_folder_the_same_way_the_handler_does(pc: dict[str, str]) -> None:
    """The registered shape must resolve refs identically — the launcher hands the
    URL to opener.cmd through the environment, not on a command line."""
    r = run_launcher(opener_url("{onedrive}/house/kitchen (2024)"), pc)
    assert r.returncode == 0 and _out(r) == f"open: {pc['od']}\\house\\kitchen (2024)"
    assert _out(run_launcher(opener_url("{sharepoint:docs}/plans"), pc)) == f"open: {pc['sp']}"
    # the accented path (the inline-PowerShell branch inside opener.cmd) too
    assert _out(run_launcher(opener_url("{onedrive}/café"), pc)) == f"missing: {pc['od']}\\café"


@windows_only
def test_a_link_carrying_a_quote_is_refused_and_nothing_else_runs(pc: dict[str, str], tmp_path: Path) -> None:
    """A quote is the character that ends an argument and starts a second command
    when a URL is re-parsed by a command interpreter (task-os#40). The app never
    sends one — ``opener_url`` percent-encodes every ref — so one that arrives is
    refused outright, and the command riding behind it must not run.

    Both spellings: raw, and percent-encoded (which the inline-PowerShell branch
    would otherwise decode back into a quote before touching the path)."""
    marker = tmp_path / "SHOULD-NOT-EXIST.txt"
    tail = f' & echo x>"{marker}" & rem '
    for url in (f'taskos://open?ref=x"{tail}"', "taskos://open?ref=" + quote(f'x"{tail}"', safe="")):
        r = run_launcher(url, pc)
        assert r.returncode == 3, f"expected a refusal for {url!r}, got {r.returncode}: {_out(r)}"
        assert "quote character" in _out(r)
        assert not marker.exists(), f"a command rode in on {url!r}"


@windows_only
def test_no_url_is_usage_error(pc: dict[str, str]) -> None:
    r = subprocess.run(f'cmd.exe /c ""{HANDLER}""', capture_output=True, timeout=30)
    assert r.returncode == 2 and "no URL given" in _decode(r.stdout)


def test_install_dry_run_prints_the_registry_plan(tmp_path: Path) -> None:
    dest = tmp_path / "la" / "task-os"
    r = subprocess.run([sys.executable, str(INSTALLER), "--dry-run", "--dest", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "install plan (dry run):" in out
    assert r"HKCU\Software\Classes\taskos" in out and "URL Protocol" in out
    assert "opener.cmd" in out and "opener.ps1" in out
    assert "mode   " in out
    assert not dest.exists()                                     # touched nothing
    r = subprocess.run([sys.executable, str(INSTALLER), "--dry-run", "--uninstall", "--dest", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert r.returncode == 0 and "uninstall plan (dry run):" in r.stdout and "opener.env" in r.stdout


def test_install_txt_is_one_install_and_one_uninstall_line() -> None:
    install, uninstall = opener_info.install_commands()
    assert install.startswith("$d=") and "HKCU:\\Software\\Classes\\taskos" in install
    assert "Invoke-WebRequest" in install and opener_info.BASE_URL_TOKEN in install
    assert "New-Item" in install and "Set-ItemProperty" in install
    assert "reg.exe" not in install and "reg add" not in install
    assert uninstall.startswith("Remove-Item") and "Classes\\taskos" in uninstall
    assert "\n" not in install and "\n" not in uninstall


def test_both_installers_register_the_launcher_and_keep_the_fallback_visible() -> None:
    """task-os#40 — the property the fix turns on, pinned in both install paths.

    ``opener.cmd`` registered directly receives the URL as a command-interpreter
    string that gets re-parsed; ``opener.ps1`` receives it as an argument. Both
    installers must prefer the launcher, and both must *announce* the fallback
    rather than degrade silently."""
    spec = importlib.util.spec_from_file_location("install_opener", INSTALLER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    dest = Path(r"C:\Users\me\AppData\Local\task-os")
    preferred = mod.command_line(dest, launcher=True)
    assert preferred.startswith("powershell.exe ") and "-File" in preferred
    assert str(dest / "opener.ps1") in preferred and '-Url "%1"' in preferred
    assert "cmd.exe" not in preferred                       # no interpreter re-parse
    fallback = mod.command_line(dest, launcher=False)
    assert fallback.startswith("cmd.exe /c ") and str(dest / "opener.cmd") in fallback
    assert "FALLBACK" in "\n".join(mod.plan(dest, uninstall=False, launcher=False))
    assert "FALLBACK" not in "\n".join(mod.plan(dest, uninstall=False, launcher=True))

    # install.txt registers the same two shapes, chosen by the same probe
    install, uninstall = opener_info.install_commands()
    assert "opener.ps1" in install and mod.SELFTEST_OK in install
    assert '-Url "%1"' in install and 'cmd.exe /c ""' in install   # preferred + fallback
    assert "FALLBACK mode" in install
    assert "opener.ps1" in uninstall and "opener.cmd" in uninstall


def test_env_template_from_placeholders() -> None:
    t = opener_info.env_template({"onedrive": "E:/od", "user": "me", "sharepoint:docs": "E:/od/T/docs - Documents"})
    assert "docs=E:\\od\\T\\docs - Documents" in t
    assert "# onedrive=E:\\od" in t and "# user=me" in t
    assert opener_info.env_template({}).count("docs=") == 1        # the example line when nothing is configured


def test_href_and_handler_agree_on_encoding() -> None:
    ref = "{onedrive}/a b/c#d"
    assert opener_url(ref) == "taskos://open?ref=" + quote(ref, safe="")
