"""A plain ``git pull`` plus ``tray.bat --restart`` updates any PC: every file a run writes is gitignored (a junctioned
``.venv`` included), the tray reclaims the port the ignored config names, no tracked script needs a signature, and
the repo's PowerShell starts under an AllSigned execution policy without overriding it.

The AllSigned runs use the ``PSExecutionPolicyPreference`` environment variable: it sets the *process*-scope policy
of that one PowerShell process tree and touches no machine or user setting.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src import ps_script
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ps_script.POWERSHELL_EXE
# host-identity-exempt: a guard over the live install, the shared helper under this machine's real profile
TRAY_HELPER = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude" / "tray" / "tray_lifecycle.ps1"
GIT_TIMEOUT_S = 60
PS_TIMEOUT_S = 120
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell execution policies are Windows only")

# What a session, a tray run, a restart, the install and the gate write inside the checkout, one file each.
RUNTIME_FILES = (
    "data/tasks.db", "data/tasks.db-wal", "data/logs/task-os.log", "data/logs/task-os-tray.log", "data/e2e-junit.xml",
    "config/config.json", "config/app_password.json", "config/sharepoint-mapping.json",
    "config/backups/config.20261121-093000.json", ".env", "mirror/x.md", "webapp/certificates/cert.pem",
    "webapp/certificates/key.pem", ".launcher-tmp/x", ".proof/x.json", ".ruff_cache/x", "app/__pycache__/x.pyc",
    "test-results/x", "tests/e2e/_shots/x.png", "tmp/scratch.txt", "x.log",
)
TRACKED_TWINS = ("config/config.sample.json", "config/sharepoint-mapping.sample.json")


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}  # a status read must never leave an index lock behind
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env,
                          timeout=GIT_TIMEOUT_S, check=True, creationflags=NO_WINDOW)
    return done.stdout


def _link_dir(link: Path, target: Path) -> None:
    """A junction on Windows (what a worktree's ``.venv`` is), a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


# ---------------------------------------------------------------- clean pull


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_every_runtime_file_and_a_linked_venv_leave_git_status_clean(tmp_path: Path) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    shutil.copy(REPO_ROOT / ".gitignore", repo / ".gitignore")
    for rel in TRACKED_TWINS:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, repo / rel)
    venv = tmp_path / "real-venv"
    (venv / "Scripts").mkdir(parents=True)
    _link_dir(repo / ".venv", venv)
    for rel in RUNTIME_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x", encoding="utf-8")
    # Only the tracked files of a clone show (nothing is committed here); every runtime file is ignored.
    listed = _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert sorted(listed) == sorted(["?? .gitignore", *(f"?? {rel}" for rel in TRACKED_TWINS)])


def test_the_gitignore_names_the_venv_without_a_trailing_slash() -> None:
    """``.venv/`` matches a folder only; a venv linked in as a junction or symlink is a file to git."""
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".venv" in lines and ".venv/" not in lines


def test_the_tray_reads_its_port_from_the_config(tmp_path: Path) -> None:
    """``launcher.py port`` is what tray.bat reclaims: the ignored config's port, never a literal."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"port": 8999}), encoding="utf-8")
    env = {**os.environ, "TASKOS_CONFIG_PATH": str(config), "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, str(REPO_ROOT / "launcher.py"), "port"], capture_output=True, text=True,
                          timeout=PS_TIMEOUT_S, env=env, cwd=tmp_path, creationflags=NO_WINDOW)
    assert done.returncode == 0 and done.stdout.strip() == "8999", done.stderr
    bat = (REPO_ROOT / "tray.bat").read_text(encoding="ascii")
    assert "OWNED_PORTS=" not in bat and "launcher.py') port" in bat


# ---------------------------------------------------------------- AllSigned


def _launch(script: Path, args: list[str], policy: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PSExecutionPolicyPreference": policy, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run([sys.executable, "-m", "src.ps_script", str(script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=PS_TIMEOUT_S, cwd=REPO_ROOT, env=env,
                          creationflags=NO_WINDOW)


@pytest.mark.parametrize("policy", ["bypass", "unrestricted", "remotesigned"])
def test_a_policy_that_runs_local_files_keeps_the_plain_file_launch(policy: str) -> None:
    argv, extra = ps_script.script_command("x.ps1", ["launch", "-Restart"], policy=policy)
    assert argv == [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", "x.ps1", "launch", "-Restart"] and extra == {}


@pytest.mark.parametrize("policy", ["allsigned", "restricted", "undefined", None])
def test_any_other_policy_or_an_unread_one_loads_the_script_as_text(policy: str | None) -> None:
    argv, extra = ps_script.script_command("x.ps1", ["launch", "", "a b"], policy=policy)
    assert argv[3] == "-Command" and "-File" not in argv and "-ExecutionPolicy" not in argv
    assert extra[ps_script.ENV_SCRIPT] == "x.ps1"
    assert extra[ps_script.ENV_ARGV].split(chr(31))[1:] == ["launch", "", "a b"]


def test_a_policy_probe_that_cannot_run_is_not_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> object:
        raise OSError("no powershell")

    monkeypatch.setattr(ps_script.subprocess, "run", boom)
    assert ps_script.effective_policy() is None


@windows_only
def test_under_allsigned_a_file_launch_is_refused_and_the_launcher_runs_it(tmp_path: Path) -> None:
    probe = tmp_path / "dir with space" / "probe.ps1"
    probe.parent.mkdir()
    probe.write_text('param([Parameter(Position = 0)][string] $Action, [string] $Name, [string] $Empty, [switch] $Flag)\n'
                     'Write-Host "action=$Action name=[$Name] empty=[$Empty] flag=$($Flag.IsPresent) root=[$PSScriptRoot]"\n'
                     "exit 7\n", encoding="utf-8")
    refused = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "AllSigned", "-File",
                              str(probe)], capture_output=True, text=True, timeout=PS_TIMEOUT_S, creationflags=NO_WINDOW)
    assert refused.returncode != 0 and "not digitally signed" in refused.stderr
    done = _launch(probe, ["launch", "-Name", "two words", "-Empty", "", "-Flag"], "AllSigned")
    assert done.returncode == 7, done.stderr
    assert f"action=launch name=[two words] empty=[] flag=True root=[{probe.parent}]" in done.stdout


@windows_only
def test_the_gate_loads_its_sibling_under_allsigned(tmp_path: Path) -> None:
    """The gate's one nested script, loaded the way verify-before-ship.ps1 writes it."""
    gate = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    loads = re.findall(r"^\. \(\[scriptblock\]::Create.*$", gate, re.MULTILINE)
    assert len(loads) == 1, loads
    harness = tmp_path / "harness.ps1"
    line = loads[0].replace("; Enter-BoxLockGate", "").replace("$PSScriptRoot", f"'{REPO_ROOT / 'scripts'}'")
    harness.write_text(f"{line}\nGet-Command Enter-BoxLockGate | Out-Null\nWrite-Host loaded\n", encoding="utf-8")
    done = _launch(harness, [], "AllSigned")
    assert done.returncode == 0 and "loaded" in done.stdout, done.stderr


@windows_only
@pytest.mark.skipif(not TRAY_HELPER.is_file(), reason="this PC has no shared tray helper")
def test_tray_bat_starts_the_shared_helper_under_allsigned(tmp_path: Path) -> None:
    """tray.bat's own -Command line, run with the read-only ``detect`` action instead of ``launch``.

    Its venv is a junction to the real one under a path no running process carries, so ``launcher.py port``
    really runs and detect finds no tray.
    """
    bat = (REPO_ROOT / "tray.bat").read_text(encoding="ascii")
    match = re.search(r'^%PS% -NoProfile -NonInteractive -Command "(.*)"\r?$', bat, re.MULTILINE)
    assert match and " launch @a " in match.group(1)
    command = match.group(1).replace(" launch @a ", " detect @a ")
    venv = tmp_path / "venv"
    _link_dir(venv, Path(sys.prefix))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"port": 8999}), encoding="utf-8")
    env = {**os.environ, "PSExecutionPolicyPreference": "AllSigned", "TRAY_PS": str(TRAY_HELPER), "TRAY_VENV": str(venv),
           "TRAY_APP_NAME": "probe", "SCRIPT_DIR_ARG": str(REPO_ROOT), "TRAY_LAUNCH": "launcher.py tray",
           "TASKOS_CONFIG_PATH": str(config)}
    done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True,
                          text=True, timeout=PS_TIMEOUT_S, env=env, creationflags=NO_WINDOW)
    assert done.returncode == 0, done.stderr
    assert "cannot be loaded" not in done.stderr and "could not read the port" not in done.stderr
    assert done.stdout.strip() == ""


def test_no_script_overrides_the_policy_or_carries_a_signature() -> None:
    """A signature appended to a tracked script turns every ``git pull`` on an AllSigned PC into a conflict."""
    scripts = [*REPO_ROOT.glob("*.bat"), *(REPO_ROOT / "scripts").glob("*.ps1"), *(REPO_ROOT / "scripts").glob("*.bat"),
               REPO_ROOT / "src" / "ps_script.py"]
    texts = {p.name: p.read_text(encoding="utf-8") for p in scripts}
    assert [n for n, t in texts.items() if re.search(r"-ExecutionPolicy\s+Bypass", t, re.I)] == []
    assert [n for n, t in texts.items() if "SIG # Begin signature block" in t] == []


def test_no_launch_starts_a_repo_or_helper_script_from_its_file() -> None:
    bat = (REPO_ROOT / "tray.bat").read_text(encoding="ascii")
    gate = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    assert not re.search(r"-File\s", re.sub(r"(?m)^REM.*$", "", bat))
    assert not re.search(r"^\s*\. \(Join-Path", gate, re.MULTILINE)
