"""Session fixtures for the Playwright e2e suite.

Isolation by construction: ``webapp`` boots a **disposable** uvicorn on a free
loopback port with ``TASKOS_DB_PATH`` → a temp database and
``TASKOS_CONFIG_PATH`` → a temp copy of the committed sample config with the
mirror / backup folders blanked (or pointed into the temp dir — see
``mirrored_webapp``), so a run never reads or writes the live ``:8448`` app,
its ``data/tasks.db``, ``config/config.json`` or the real mirror folder.

Auth (Step 7): the browser reaches the disposable instance over loopback,
which ``src.auth`` treats as the owner — no token, cookie or env switch is
needed; there is deliberately no ``TASKOS_AUTH_DISABLED`` flag. The
non-loopback gate is proven at unit level (``tests/test_auth.py``) with a
spoofed client address; story 07 walks the /login page against an instance
booted with a temp config that carries a token.

``TASKOS_E2E_LIVE=1`` is the one loudly-named opt-in: the suite then runs
*read-only* against the live ``http://127.0.0.1:8448`` instead of booting
(never a kill — reclaiming the port is ``tray.bat --restart``'s job). The
check → refuse → log policy is the vendored ``_e2e_live_guard.py``.

``seeded_webapp`` boots a second disposable instance over the synthetic
fixture (``tests/fixtures/seed.py``) for the stories that need data on
screen (Step 4 on); ``webapp`` stays empty for story 01. Story 22 boots its
own pair over ``tests/fixtures/whisper_fake.FakeWhisper`` (never the fleet's
real hub or whisper server — both ``voice`` endpoints are blank suite-wide). ``mirrored_webapp``
(story 06) is a seeded instance whose ``mirror.dir`` / ``backup_dir`` are
temp folders the test can edit and list. ``issues_webapp`` (story 08) is a
seeded instance whose issue provider is the file-backed fake
(``TASKOS_ISSUE_PROVIDER=fake`` over a temp JSON "forge" the test edits —
never ``gh``, never the network).

Screenshots: ``shots`` yields ``docs/screenshots`` so a story test saves its
numbered proof there directly (the public repo carries them; the fixture DB
is synthetic/empty, never personal data). A story captures through ``shot()``
— never ``page.screenshot`` — so two runs against one commit produce
byte-identical files (#134); see the "deterministic capture" section below.

``pytest_sessionfinish`` runs the vendored leaked-browser sweep (#203) once
every fixture — pytest-playwright's ``browser`` included — has torn down.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import IO

import pytest
from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.conftest import write_test_config
from tests.e2e._browser_sweep import sweep_browser_helpers
from tests.e2e._e2e_live_guard import require_disposable_instance

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"
LIVE_PORT = 8448
LIVE_ENV = "TASKOS_E2E_LIVE"
LOOP_FACTORY = "app.webapp.event_loop:selector_loop_factory"

# Bounded Playwright waits: 15 s fails fast with a TimeoutError naming the
# locator instead of stacking opaque 30 s waits (project-scaffolding#61).
_DEFAULT_TIMEOUT_MS = int(os.environ.get("E2E_DEFAULT_TIMEOUT_MS", "15000"))

# How long `settle()` gives the network to go quiet before a capture. Short on
# purpose: the app opens no socket and polls nothing, so a page that is still
# fetching after this has something else wrong with it.
_SETTLE_NETWORK_MS = 5000

# The session's own "now" (#134). One date for the whole run — the seed anchors
# on it and every disposable instance pins `TASKOS_CLOCK` to it — so a task
# touched during a story is stamped 09:00 rather than the minute the run
# happened to reach it, and two runs of the same commit write byte-identical
# timestamps into the gallery. The date still moves day to day (the seed's
# relative dues have to stay believable on screen, so it is deliberately not
# frozen to a fixed past day); the time of day no longer does. Sampling it once
# here also keeps a run that straddles midnight self-consistent.
E2E_ANCHOR = date.today()
E2E_CLOCK = (datetime.combine(E2E_ANCHOR, datetime.min.time())
             .replace(hour=9).astimezone().isoformat(timespec="seconds"))


#: One stable working root for the whole suite (#134). `tmp_path_factory`
#: numbers its base directory per run — `pytest-9167`, `pytest-9168`, … — and
#: stories 09 and 10 put those absolute paths on screen, so every run rewrote
#: those shots for no reason anyone could review. A fixed name under the same
#: system temp root keeps the paths identical run to run. It stays under the
#: system temp dir on purpose: a repo-local root put the SQLite file on the
#: checkout's own drive and slowed writes enough to lose races the stories were
#: already winning only narrowly.
E2E_WORK_ROOT = Path(tempfile.gettempdir()) / "taskos-e2e"


def e2e_workdir(name: str) -> Path:
    """An empty, same-path-every-run working directory for one disposable instance.

    A leftover from a previous run is removed rather than reused — a stale
    database would make the seed refuse to fill it. Left in place afterwards:
    each instance's `webapp.log` is the post-mortem for a story that failed.
    """
    work = E2E_WORK_ROOT / name
    shutil.rmtree(work, ignore_errors=True)
    if work.exists():   # still there → something is holding it open, say so now
        raise RuntimeError(f"could not clear the e2e work dir {work} — is a previous instance still running?")
    work.mkdir(parents=True, exist_ok=True)
    return work


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthz(base: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2) as res:
                if res.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


def _terminate(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:  # noqa: BLE001 — best effort
                pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:  # noqa: BLE001 — best effort
        pass


def _boot(work: Path, db_path: Path, config_path: Path | None = None,
          extra_env: dict[str, str] | None = None) -> tuple[subprocess.Popen, str, IO[str]]:
    """Start a disposable uvicorn on a free loopback port over ``db_path``.

    ``config_path`` defaults to a temp copy of the sample with the mirror and
    backup folders blanked, so the instance never touches a real synced folder
    (and no auth token → the instance is loopback-only, which is exactly what
    the browser is). Story 07 passes a temp config carrying a token to walk
    the /login page. The issue provider is forced off unless ``extra_env``
    picks one (story 08 picks the fake). ``TASKOS_CLOCK`` pins the instance's
    clock to ``E2E_CLOCK`` so the timestamps a story writes — activity rows,
    comments, ``done_at`` — land on the shot as 09:00 rather than the minute
    the run reached them (#134).
    """
    port = _free_tcp_port()
    print(f"[e2e] booting disposable instance on 127.0.0.1:{port} (db {db_path})")
    log: IO[str] = (work / "webapp.log").open("w", encoding="utf-8")
    if config_path is None:
        config_path = write_test_config(work / "config.json")
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TASKOS_DB_PATH": str(db_path),
        "TASKOS_CONFIG_PATH": str(config_path),
        "TASKOS_ISSUE_PROVIDER": "none",
        "TASKOS_CLOCK": E2E_CLOCK,
        **(extra_env or {}),
    }
    cmd = [
        sys.executable, "-m", "uvicorn", "app.webapp.server:app",
        "--host", "127.0.0.1", "--port", str(port),
        "--log-level", "warning", "--loop", LOOP_FACTORY,
    ]
    kwargs: dict = dict(cwd=str(REPO_ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **kwargs)
    base = f"http://127.0.0.1:{port}"
    if not _wait_healthz(base, timeout=20):
        _terminate(proc)
        log.close()
        tail = (work / "webapp.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        pytest.fail(f"disposable webapp did not answer {base}/healthz within 20s\n{tail}")
    return proc, base, log


# ------------------------------------------------------- HTTP from a story
# Every story reads the instance's own API to set up or confirm what the
# browser then shows. One `_get` / `_post` here, not one per story file: six
# copies had already drifted apart (two of them silently dropped the status
# assertion — issue #35).


def _get(base: str, path: str) -> dict:
    """GET a JSON endpoint on the instance under test.

    ``urlopen`` already raises on 4xx/5xx; the assertion is what catches a 2xx
    that is not the ``200`` every story here expects (a 201/204 answer would
    otherwise be parsed as if it were the body asked for).
    """
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as res:
        assert res.status == 200
        return json.loads(res.read().decode("utf-8"))


def _post(base: str, path: str) -> dict:
    """POST an empty JSON body — the reindex / sync triggers a story fires so it
    is deterministic instead of racing the startup thread. The long timeout is
    for a cold folder reindex."""
    req = urllib.request.Request(f"{base}{path}", data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


# The stories that walk a `taskos://` folder link (09, 10) cannot let the OS
# handler fire: this init script swallows the click and records the href on
# `window.__taskosClicks` instead.
INTERCEPT = (
    "document.addEventListener('click', function (e) {"
    "  const a = e.target.closest && e.target.closest('a[href^=\"taskos:\"]');"
    "  if (a) { window.__taskosClicks = (window.__taskosClicks || []).concat(a.getAttribute('href')); e.preventDefault(); }"
    "}, true);"
)


@pytest.fixture(scope="session")
def webapp() -> Iterator[str]:
    """Base URL of the instance under test — disposable, **empty** DB by default."""
    if os.environ.get(LIVE_ENV) == "1":
        require_disposable_instance(LIVE_PORT, LIVE_ENV)
        base = f"http://127.0.0.1:{LIVE_PORT}"
        if not _wait_healthz(base, timeout=5):
            pytest.exit(f"{LIVE_ENV}=1 but nothing answers {base}/healthz", returncode=2)
        yield base
        return

    work = e2e_workdir("empty")
    proc, base, log = _boot(work, work / "tasks.db")
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="session")
def seeded_webapp() -> Iterator[str]:
    """A second disposable instance over the **synthetic seed** (tests/fixtures/seed.py).

    Story tests from Step 4 on walk real data; story 01 keeps the empty
    instance. Never available against the live app (``TASKOS_E2E_LIVE=1``):
    the seed refuses a database that already has tasks, and the live DB is
    the user's — those tests skip loudly instead.
    """
    if os.environ.get(LIVE_ENV) == "1":
        pytest.skip(f"{LIVE_ENV}=1: the seeded fixture never runs against the live database")
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("seeded")
    db = work / "tasks.db"
    seed_db(db, E2E_ANCHOR)
    proc, base, log = _boot(work, db)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


class MirroredInstance:
    """What story 06 needs: the base URL plus the folders the instance writes."""

    def __init__(self, base: str, mirror_dir: Path, backup_dir: Path, db: Path) -> None:
        self.base = base
        self.mirror_dir = mirror_dir
        self.backup_dir = backup_dir
        self.db = db


@pytest.fixture(scope="session")
def mirrored_webapp() -> Iterator[MirroredInstance]:
    """A seeded disposable instance with ``mirror.dir`` / ``backup_dir`` under a temp folder.

    The one instance that runs on the **real** clock (``TASKOS_CLOCK`` blanked).
    The mirror's import-conflict rule is *defined* in terms of a clock that
    advances — the DB wins when the field's latest ``activity.ts`` is later than
    the file's recorded ``exported_at`` — so a frozen clock makes those two
    stamps equal and the conflict story cannot happen at all. Story 06's five
    shots are the stated exception to the byte-identical gallery (#134); every
    other story runs pinned.
    """
    if os.environ.get(LIVE_ENV) == "1":
        pytest.skip(f"{LIVE_ENV}=1: the mirrored fixture never runs against the live database")
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("mirror")
    db = work / "tasks.db"
    seed_db(db, E2E_ANCHOR)
    mirror_dir = work / "mirror"
    backup_dir = work / "backup"
    mirror_dir.mkdir()
    config = write_test_config(work / "config.json", dir=str(mirror_dir), backup_dir=str(backup_dir))
    proc, base, log = _boot(work, db, config, extra_env={"TASKOS_CLOCK": ""})
    try:
        yield MirroredInstance(base, mirror_dir, backup_dir, db)
    finally:
        _terminate(proc)
        log.close()


FAKE_ISSUES = [
    {"repo": "example/garden-bot", "number": 12, "title": "Fix watering schedule drift", "state": "open",
     "url": "https://github.com/example/garden-bot/issues/12", "labels": ["bug"],
     "updated_at": "2026-08-16T09:00:00Z", "body": "The cron uses local time; drift after DST."},
    {"repo": "example/garden-bot", "number": 14, "title": "Add soil-moisture sensor to the loop", "state": "open",
     "url": "https://github.com/example/garden-bot/issues/14", "labels": ["enhancement"],
     "updated_at": "2026-08-17T07:00:00Z", "body": "Read the capacitive sensor every 10 min and skip watering when wet."},
    {"repo": "example/home-dashboard", "number": 3, "title": "Dark theme contrast on the energy card", "state": "open",
     "url": "https://github.com/example/home-dashboard/issues/3", "labels": ["bug", "design"],
     "updated_at": "2026-08-15T18:30:00Z", "body": ""},
]


class IssuesInstance:
    """What story 08 needs: the base URL plus the fake forge file the test edits."""

    def __init__(self, base: str, forge: Path, db: Path) -> None:
        self.base = base
        self.forge = forge
        self.db = db

    def issues(self) -> list[dict]:
        import json

        return json.loads(self.forge.read_text(encoding="utf-8"))["issues"]

    def set_issue(self, repo: str, number: int, **changes) -> None:
        import json

        data = json.loads(self.forge.read_text(encoding="utf-8"))
        for row in data["issues"]:
            if row["repo"] == repo and row["number"] == number:
                row.update(changes)
        self.forge.write_text(json.dumps(data, indent=1), encoding="utf-8")


@pytest.fixture(scope="session")
def issues_webapp() -> Iterator[IssuesInstance]:
    """A seeded disposable instance whose issue provider is the file-backed fake."""
    if os.environ.get(LIVE_ENV) == "1":
        pytest.skip(f"{LIVE_ENV}=1: the issues fixture never runs against the live database")
    import json

    from tests.fixtures.seed import seed_db

    work = e2e_workdir("issues")
    db = work / "tasks.db"
    seed_db(db, E2E_ANCHOR)
    forge = work / "forge.json"
    forge.write_text(json.dumps({"issues": FAKE_ISSUES, "error": None}, indent=1), encoding="utf-8")
    proc, base, log = _boot(work, db, extra_env={"TASKOS_ISSUE_PROVIDER": "fake", "TASKOS_ISSUE_FAKE_PATH": str(forge)})
    try:
        yield IssuesInstance(base, forge, db)
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="session")
def shots() -> Path:
    """Where story tests save their numbered proof screenshots."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return SHOTS_DIR


# ------------------------------------------------ deterministic capture (#134)
# Every story shot goes through `shot()`, never `page.screenshot` directly: two
# runs of the suite against the same commit have to produce byte-identical
# files, or the gallery cannot tell a visual regression from capture noise.
# Three things moved between runs before this existed — an animation still in
# flight (the vendored nav's 1.8 s-delayed boot reveal was the loudest), a pane
# whose rows had not been fetched or painted yet, and a scroll still gliding to
# its target — so `settle()` closes all three and the capture itself hands
# Playwright `animations="disabled"` (finite ones fast-forwarded to their end
# state, infinite ones — the `.is-busy` spinner — parked at frame zero).

_SETTLE_JS = """
async () => {
  const raf = () => new Promise(r => requestAnimationFrame(() => r()));
  try { if (document.fonts) await document.fonts.ready; } catch (e) { /* no-op */ }
  const pending = Array.from(document.images).filter(i => !i.complete);
  if (pending.length) {
    await Promise.all(pending.map(i => new Promise(r => {
      i.addEventListener('load', r, { once: true });
      i.addEventListener('error', r, { once: true });
    })));
  }
  // Let every finite animation actually END rather than leaning on Playwright's
  // `animations="disabled"` to seek it there. Both land on the same frame, but
  // an animation still running keeps its element on a composited layer, and a
  // composited edge rasterises a shade differently from a settled one — a few
  // pixels off by 1/255 along the nav pill, enough to move the file. Infinite
  // ones (the `.is-busy` spinner) never finish and are left to Playwright.
  const running = document.getAnimations().filter(a => {
    const timing = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
    return timing && timing.iterations !== Infinity && timing.endTime !== Infinity;
  });
  if (running.length) {
    await Promise.race([
      Promise.all(running.map(a => a.finished.catch(() => {}))),
      new Promise(r => setTimeout(r, 4000)),
    ]);
  }
  // One string standing for "what the next frame would paint": how much DOM
  // there is, how tall it is, and where every scroller sits.
  const sample = () => {
    const parts = [window.scrollX, window.scrollY,
                   document.documentElement.scrollHeight,
                   document.getElementsByTagName('*').length];
    for (const el of document.querySelectorAll('*')) {
      if (el.scrollTop || el.scrollLeft) parts.push(el.scrollTop, el.scrollLeft);
    }
    return parts.join('|');
  };
  let previous = null, stable = 0;
  for (let i = 0; i < 120 && stable < 3; i++) {
    await raf();
    const current = sample();
    stable = current === previous ? stable + 1 : 0;
    previous = current;
  }
  await raf();
  await raf();
}
"""


def settle(page: Page) -> None:
    """Block until the page has stopped moving.

    Network first (a pane that renders off a `fetch` must have its rows before
    the shutter opens), then fonts and images, then every finite animation to
    its end, then three consecutive animation frames in which neither the DOM
    size nor any scroll offset changed. The network wait is bounded and
    swallowed rather than fatal: a story that deliberately captures
    mid-request would otherwise fail on the wait instead of on its own
    assertion.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=_SETTLE_NETWORK_MS)
    except PlaywrightTimeoutError:
        pass
    page.evaluate(_SETTLE_JS)


def shot(page: Page, path: Path, *, full_page: bool = False) -> None:
    """Save one story proof screenshot to *path*, deterministically."""
    settle(page)
    page.screenshot(path=str(path), full_page=full_page, animations="disabled", caret="hide")


def _press(page: Page, target: Locator) -> None:
    """Tap on a touch context, click otherwise — the gesture a real user makes."""
    if page.evaluate("() => 'ontouchstart' in window"):
        target.tap()
    else:
        target.click()


def _table_pane_view(page: Page, view: str, host: str) -> None:
    """Put the Table pane on one of its two drawings (#161).

    The Tree stopped being a nav destination when it became the Table pane's
    second view: reaching it is *tab, then toggle*, and it is the strip's
    segmented control that switches — never a `data-tab='tree'` click, which
    no longer matches anything.
    """
    _press(page, page.locator("nav.tabs .tab[data-tab='table']"))
    expect(page.locator("#paneTable")).to_be_visible()
    seg = page.locator(f"#tableViewToggle .view-seg[data-view='{view}']")
    _press(page, seg)
    expect(seg).to_have_attribute("aria-pressed", "true")
    expect(page.locator(host)).to_be_visible()


def tree_view(page: Page) -> None:
    """Open the Table tab on its Tree view; the outline is on screen after."""
    _table_pane_view(page, "tree", "#paneTable #treeHost")


def table_view(page: Page) -> None:
    """Open the Table tab on its grid/rows view — the other half of the pair."""
    _table_pane_view(page, "table", "#paneTable #tableHost")


@pytest.fixture(autouse=True)
def _bound_default_timeouts(context) -> None:
    context.set_default_timeout(_DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Advisory sweep of browser helpers this run orphaned inside this checkout."""
    result = sweep_browser_helpers(REPO_ROOT)
    print(f"\n{result.summary()}")
    for entry in result.killed:
        print(f"  reclaimed leaked helper: {entry}")
    # Playwright's own scratch dir under the checkout — nothing of ours lives there.
    shutil.rmtree(REPO_ROOT / "test-results", ignore_errors=True)
