"""The per-PC folder opener (``opener/``, Step 9), run **for real** through
``cmd.exe`` — the environment points at a temp tree (``OneDrive``,
``OneDriveCommercial``, ``USERNAME``, ``LOCALAPPDATA``) and
``TASKOS_OPENER_DRYRUN=1`` makes the handler print ``open: <path>`` /
``missing: <path>`` / ``reveal: <path>`` / ``refused: <path>`` instead of
launching anything. Windows-only (skipped elsewhere); ``install_opener.py
--dry-run`` and ``src/opener.py`` run anywhere."""

from __future__ import annotations

import base64
import importlib.util
import inspect
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from src import opener as opener_info
from src.no_window import NO_WINDOW
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
    return subprocess.run(cmd, input=b"\r\n", capture_output=True, env=env, timeout=30,
                          creationflags=NO_WINDOW)


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
        creationflags=NO_WINDOW,
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


def _lines(r: subprocess.CompletedProcess) -> list[str]:
    return [ln.strip() for ln in _decode(r.stdout).splitlines() if ln.strip()]


def _transcripts(tmp_path: Path) -> tuple[Path, Path]:
    """A fake ``.claude/projects``: the transcript owning ``session_01ResumeMe``,
    a decoy, and a NEWER transcript that merely mentions the id (a grep result
    quoted in a conversation) — which must not shadow the owner, since only the
    session-url marker identifies it."""
    projects = tmp_path / "projects"
    proj = projects / "E--automation-demo"
    proj.mkdir(parents=True)
    repo_dir = tmp_path / "demo-repo"
    repo_dir.mkdir()
    cwd_json = str(repo_dir).replace("\\", "\\\\")
    (proj / "11111111-2222-3333-4444-555555555555.jsonl").write_text(
        f'{{"cwd":"{cwd_json}","url":"https://claude.ai/code/session_01ResumeMe"}}\n',
        encoding="utf-8",
    )
    (proj / "aaaaaaaa-0000-0000-0000-000000000000.jsonl").write_text(
        f'{{"cwd":"{cwd_json}","url":"https://claude.ai/code/session_01SomethingElse"}}\n',
        encoding="utf-8",
    )
    time.sleep(0.05)
    (proj / "bbbbbbbb-0000-0000-0000-000000000000.jsonl").write_text(
        f'{{"cwd":"{cwd_json}","url":"https://claude.ai/code/session_01SomethingElse",'
        '"text":"we grepped and saw session_01ResumeMe in the logs"}\n',
        encoding="utf-8",
    )
    return projects, repo_dir


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
def test_only_documents_open_anything_else_is_shown_in_its_folder(pc: dict[str, str]) -> None:
    """A file goes to its default app only when its type is on the document
    list; any other file (a program, a script some installed app would run, a
    name with no extension that a same-named .cmd could stand in for) is shown
    selected in its folder instead — never started. A ref that starts on another
    computer, or names a stream past the file, is refused before it is touched.
    Pure-cmd branch, inline-PowerShell one (an accented name) and the launcher."""
    od = Path(pc["od"])
    for name in ("tool.exe", "script.bat", "link.lnk", "npm", "npm.cmd", "deploy.sh",
                 "café.exe", "café.sh", "mail.msg", "réunion.txt", "Report.PDF"):
        (od / name).write_bytes(b"x")
    unc = "\\\\unreachable.invalid\\"
    for ref, line in (
        ("{onedrive}/tool.exe", f"reveal: {od / 'tool.exe'}"),
        ("{onedrive}/TOOL.EXE", f"reveal: {od / 'tool.exe'}"),
        ("{onedrive}/tool.exe.", f"reveal: {od / 'tool.exe'}"),
        ("{onedrive}/tool.exe ", f"reveal: {od / 'tool.exe'}"),
        ("{onedrive}/script.bat", f"reveal: {od / 'script.bat'}"),
        ("{onedrive}/link.lnk", f"reveal: {od / 'link.lnk'}"),
        ("{onedrive}/npm", f"reveal: {od / 'npm'}"),
        ("{onedrive}/deploy.sh", f"reveal: {od / 'deploy.sh'}"),
        ("{onedrive}/café.exe", f"reveal: {od / 'café.exe'}"),
        ("{onedrive}/café.sh", f"reveal: {od / 'café.sh'}"),
        ("{onedrive}/notes.txt::$DATA", f"refused: {od / 'notes.txt::$DATA'}"),
        ("{onedrive}/notes.txt:x.cmd", f"refused: {od / 'notes.txt:x.cmd'}"),
        ("{onedrive}/café.txt:x", f"refused: {od / 'café.txt:x'}"),
        ("//unreachable.invalid/share/x.txt", f"refused: {unc}share\\x.txt"),
        (unc + "share", f"refused: {unc}share"),
        ("//unreachable.invalid/café", f"refused: {unc}café"),
        ("{onedrive}/notes.txt", f"open: {od / 'notes.txt'}"),
        ("{onedrive}/Report.PDF", f"open: {od / 'Report.PDF'}"),
        ("{onedrive}/mail.msg", f"open: {od / 'mail.msg'}"),
        ("{onedrive}/réunion.txt", f"open: {od / 'réunion.txt'}"),
        ("{onedrive}/house", f"open: {od / 'house'}"),
        # an unmapped {sharepoint:<name>} keeps the placeholder-missing notice
        ("{sharepoint:unmapped}/plans", "missing: {sharepoint:unmapped}\\plans"),
        ("{sharepoint:unmapped}/café", "missing: {sharepoint:unmapped}\\café"),
    ):
        r = run_opener(opener_url(ref), pc)
        assert r.returncode == 0 and _out(r) == line, f"{ref!r}: {_out(r)}"
    assert _out(run_launcher(opener_url("{onedrive}/script.bat"), pc)) == f"reveal: {od / 'script.bat'}"
    # a wildcard names no one file: refused in both branches (raw in the URL → cmd)
    for url, shown in (("taskos://open?ref=%7Bonedrive%7D%2Ft*.exe", od / "t*.exe"),
                       ("taskos://open?ref=%7Bonedrive%7D%2Ftool.ex?", od / "tool.ex?"),
                       (opener_url("{onedrive}/caf*.exe"), od / "caf*.exe")):
        assert _out(run_opener(url, pc)) == f"refused: {shown}", url
    # the refusal for real: visible, nothing started, its own exit code
    for ref in ("//unreachable.invalid/share", "//unreachable.invalid/café"):
        r = run_opener(opener_url(ref), pc, dryrun=False)
        assert r.returncode == 6 and "Nothing was opened" in _decode(r.stdout), ref


@windows_only
def test_a_file_under_a_share_placeholder_is_a_file_not_a_folder(pc: dict[str, str]) -> None:
    """``if exist "<path>\\"`` is true for a plain file on a network share, so
    folder-or-file is decided by attributes: a program under a placeholder that
    opener.env maps to a share is revealed, a document there opens, and a folder
    there opens in Explorer — in both branches. Reached over this PC's own
    administrative share; skipped where that share is off."""
    od = Path(pc["od"])
    share = f"\\\\localhost\\{od.drive[0]}$" + str(od)[2:]
    if not os.path.isdir(share):
        pytest.skip("this PC's administrative share is not reachable")
    for name in ("tool.cmd", "café.cmd"):
        (od / name).write_bytes(b"x")
    env_file = Path(pc["la"]) / "task-os" / "opener.env"
    env_file.write_text(env_file.read_text(encoding="utf-8") + f"scr={share}\n", encoding="utf-8")
    for ref, line in (
        ("{scr}/tool.cmd", f"reveal: {share}\\tool.cmd"),
        ("{scr}/café.cmd", f"reveal: {share}\\café.cmd"),
        ("{scr}/notes.txt", f"open: {share}\\notes.txt"),
        ("{scr}/house", f"open: {share}\\house"),
    ):
        assert _out(run_opener(opener_url(ref), pc)) == line, ref


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
def test_resume_finds_the_transcript_and_targets_its_repo(pc: dict[str, str], tmp_path: Path) -> None:
    """taskos://resume?session=… (#77): the launcher maps the web session id to
    the local transcript's uuid + the repo it ran in ("cwd"), dry-run printing
    what it would reopen instead of launching a terminal."""
    projects, repo_dir = _transcripts(tmp_path)
    r = run_launcher("taskos://resume?session=session_01ResumeMe", pc,
                     TASKOS_OPENER_PROJECTS=str(projects))
    assert r.returncode == 0, _decode(r.stdout) + _decode(r.stderr)
    assert _lines(r)[0] == f"resume: 11111111-2222-3333-4444-555555555555 in {repo_dir}"
    # the shape a browser actually sends: the scheme normalised with a slash
    # before the query (like open/?ref=) — same result
    r = run_launcher("taskos://resume/?session=session_01ResumeMe", pc,
                     TASKOS_OPENER_PROJECTS=str(projects))
    assert _lines(r)[0] == f"resume: 11111111-2222-3333-4444-555555555555 in {repo_dir}"


@windows_only
def test_resume_launches_one_tab_in_the_repo(pc: dict[str, str], tmp_path: Path) -> None:
    """The launch argv itself (#227). ``;`` is Windows Terminal's own new-tab
    delimiter and it splits on one *before* the argument's quoting is considered,
    so the ``;``-separated ``-Command`` this used to build arrived as three tabs:
    a bare prompt, a tab that tried to run ``Write-Host`` as an executable, and a
    ``claude`` that never saw ``-d`` and so started in ``system32``.

    The dry run used to return before the launch code, which is how that shipped
    with green tests; it prints the argv now so this can assert on it. The
    payload rides as one base64 token, an alphabet with no ``;`` — decoded back
    here, so an encoding that merely *looks* opaque cannot pass."""
    projects, repo_dir = _transcripts(tmp_path)
    uuid = "11111111-2222-3333-4444-555555555555"

    r = run_launcher("taskos://resume?session=session_01ResumeMe", pc,
                     TASKOS_OPENER_PROJECTS=str(projects), TASKOS_OPENER_WT="1")
    assert r.returncode == 0, _decode(r.stdout) + _decode(r.stderr)
    exec_line = next(ln for ln in _lines(r) if ln.startswith("resume-exec: "))
    # one tab, opened in the repo the transcript recorded. A `;` wt is meant to
    # take literally arrives escaped (`\;`) — drop those before looking for a
    # bare one, which is the character that would split the tab.
    assert ";" not in exec_line.replace("\\;", ""), exec_line
    assert exec_line.startswith(f"resume-exec: wt -d {repo_dir} "
                                "powershell -NoProfile -NoExit -EncodedCommand ")
    # and it carries the whole command, both echoes included, not a truncated one
    inner = base64.b64decode(exec_line.rsplit(" ", 1)[1]).decode("utf-16-le")
    assert inner.count("Write-Host") == 2 and str(repo_dir) in inner
    assert inner.endswith(f"claude --resume {uuid}")

    # the wt-less fallback keeps its own shape: same payload, -WorkingDirectory
    r = run_launcher("taskos://resume?session=session_01ResumeMe", pc,
                     TASKOS_OPENER_PROJECTS=str(projects), TASKOS_OPENER_WT="0")
    exec_line = next(ln for ln in _lines(r) if ln.startswith("resume-exec: "))
    assert ";" not in exec_line.replace("\\;", ""), exec_line
    assert exec_line.startswith(f"resume-exec: powershell -WorkingDirectory {repo_dir} "
                                "-NoProfile -NoExit -EncodedCommand ")
    assert base64.b64decode(exec_line.rsplit(" ", 1)[1]).decode("utf-16-le") == inner


@windows_only
def test_resume_unknown_session_falls_back_to_the_web(pc: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    r = run_launcher("taskos://resume?session=session_01NotHere", pc,
                     TASKOS_OPENER_PROJECTS=str(projects))
    assert r.returncode == 0
    assert _out(r) == "resume-web: https://claude.ai/code/session_01NotHere"


@windows_only
def test_resume_via_the_cmd_fallback_says_so(pc: dict[str, str]) -> None:
    """The pure-cmd fallback registration cannot search transcripts or launch a
    terminal — it must say so visibly, never degrade silently."""
    r = run_opener("taskos://resume?session=session_01X", pc)
    assert r.returncode == 5 and "resume-unsupported" in _out(r)


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
    r = subprocess.run(f'cmd.exe /c ""{HANDLER}""', capture_output=True, timeout=30,
                       creationflags=NO_WINDOW)
    assert r.returncode == 2 and "no URL given" in _decode(r.stdout)


def test_install_dry_run_prints_the_registry_plan(tmp_path: Path) -> None:
    dest = tmp_path / "la" / "task-os"
    r = subprocess.run([sys.executable, str(INSTALLER), "--dry-run", "--dest", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", timeout=90,
                       creationflags=NO_WINDOW)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "install plan (dry run):" in out
    assert r"HKCU\Software\Classes\taskos" in out and "URL Protocol" in out
    assert "opener.cmd" in out and "opener.ps1" in out
    assert "mode   " in out
    assert not dest.exists()                                     # touched nothing
    r = subprocess.run([sys.executable, str(INSTALLER), "--dry-run", "--uninstall", "--dest", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", timeout=90,
                       creationflags=NO_WINDOW)
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
    # task-os#130: wrapped in conhost.exe --headless so ShellExecute allocates
    # no visible console (measured on this PC - plain powershell.exe, even
    # -WindowStyle Hidden, still flashes a Windows Terminal window)
    assert preferred.startswith("conhost.exe --headless powershell.exe ") and "-File" in preferred
    assert str(dest / "opener.ps1") in preferred and '-Url "%1"' in preferred
    assert "cmd.exe" not in preferred                       # no interpreter re-parse
    fallback = mod.command_line(dest, launcher=False)
    assert fallback.startswith("cmd.exe /c ") and str(dest / "opener.cmd") in fallback
    assert "FALLBACK" in "\n".join(mod.plan(dest, uninstall=False, launcher=False))
    assert "FALLBACK" not in "\n".join(mod.plan(dest, uninstall=False, launcher=True))

    # the self-test probe deliberately stays unwrapped (bare powershell.exe):
    # conhost.exe --headless swallows the caller's stdout capture, so probing
    # through it would always read as "cannot run the launcher"
    probe_src = inspect.getsource(mod.launcher_runs)
    assert '"powershell.exe"' in probe_src and "conhost" not in probe_src

    # install.txt registers the same two shapes, chosen by the same probe
    install, uninstall = opener_info.install_commands()
    assert "opener.ps1" in install and mod.SELFTEST_OK in install
    assert "conhost.exe --headless powershell.exe" in install       # registration
    assert '-Url "%1"' in install and 'cmd.exe /c ""' in install   # preferred + fallback
    assert "FALLBACK mode" in install
    assert "opener.ps1" in uninstall and "opener.cmd" in uninstall
    # the self-test line itself must stay unwrapped, same reasoning as above
    selftest_line = next(ln for ln in install.split(";") if "taskos://selftest" in ln)
    assert "conhost" not in selftest_line and "powershell.exe" in selftest_line


def test_registration_mode_distinguishes_stale_from_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """task-os#130: a launcher registered before the conhost.exe --headless wrap
    landed is still a launcher, but it flashes a console every open - report it
    as stale so Settings tells the PC to re-run the install command, the same
    as a fallback install."""
    monkeypatch.setattr(
        opener_info, "_registered_command",
        lambda: 'conhost.exe --headless powershell.exe -File "C:\\x\\opener.ps1" -Url "%1"',
    )
    assert opener_info.registration_mode() == "launcher"
    monkeypatch.setattr(
        opener_info, "_registered_command",
        lambda: 'powershell.exe -File "C:\\x\\opener.ps1" -Url "%1"',
    )
    assert opener_info.registration_mode() == "launcher-stale"
    monkeypatch.setattr(
        opener_info, "_registered_command",
        lambda: 'cmd.exe /c ""C:\\x\\opener.cmd" "%1""',
    )
    assert opener_info.registration_mode() == "fallback"
    monkeypatch.setattr(opener_info, "_registered_command", lambda: None)
    assert opener_info.registration_mode() is None


def test_env_template_from_placeholders() -> None:
    t = opener_info.env_template({"onedrive": "E:/od", "user": "me", "sharepoint:docs": "E:/od/T/docs - Documents"})
    assert "docs=E:\\od\\T\\docs - Documents" in t
    assert "# onedrive=E:\\od" in t and "# user=me" in t
    assert opener_info.env_template({}).count("docs=") == 1        # the example line when nothing is configured


def test_href_and_handler_agree_on_encoding() -> None:
    ref = "{onedrive}/a b/c#d"
    assert opener_url(ref) == "taskos://open?ref=" + quote(ref, safe="")
