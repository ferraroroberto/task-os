"""Issue sync — the forge's open issues become (and stay) coding tasks.

:func:`sync_once` is the whole reconciliation, one pass, over an open
connection and an :class:`~src.issues.base.IssueProvider`:

1. ``provider.list_open_assigned()`` — the open issues assigned to me. A
   provider failure aborts the pass with the error recorded (nothing is
   changed on a bad read — never "no issues" from an empty answer).
2. Every open issue **without** a local ref → a new task: ``title`` = the issue
   title, ``code`` = ``<repo>#<n>`` (short repo name), ``status = inbox``,
   ``description`` = the issue body (trimmed), a ``links`` row (kind
   ``issue``) and the ``issue_refs`` row that makes it ``coding``. Dedupe key
   is (provider, repo, number) — a re-run touches nothing it already made.
3. Every open issue **with** a ref: ``last_synced`` moves; a **title change on
   the forge lands on the task** (activity ``title`` by ``sync`` — the issue's
   title is canonical for a coding task, rename it there); a ref that was
   ``closed`` and is open again → the task is **reopened**: status ``todo``
   (activity by ``sync``) if it was done / cancelled.
4. Every ref that is ``open`` (or never synced) but **missing** from the list
   is confirmed with ``provider.get()`` before anything happens: ``closed`` →
   ref ``closed`` + the task ``done`` (skipped if already done / cancelled;
   activity by ``sync``); still ``open`` (unassigned, another owner) → only
   ``last_synced`` moves; a lookup error is recorded and the task is left as
   is. Refs already ``closed`` are not polled — a reopen shows up in step 3.

Nothing is ever written back to the forge. ``actor = "sync"`` on every
activity row and ``created_by`` of every task the sync creates.

:class:`IssueSyncService` runs it in-app: a thread started from the webapp
lifespan (like the backup scheduler) — first pass 10 s after startup, then
every ``issues.sync_minutes`` — plus ``run_now()`` for ↻ / ``POST
/api/issues/sync`` / ``tasks issues sync``. ``status()`` is what
``/api/issues/status``, the Settings card and ``tasks issues status`` show:
provider, configured?, last sync, counts, last error, next run. It also keeps
the last-seen :class:`IssueInfo` per ref (labels, updated_at) for the drawer
panel — an in-memory cache, warm after the first pass.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src import tasks_repo as repo
from src.config import AppConfig
from src.db import connect
from src.issues import IssueInfo, IssueProvider, IssueProviderError, get_provider, short_repo

logger = logging.getLogger(__name__)

SYNC_ACTOR = "sync"
INITIAL_DELAY_S = 10.0
DESCRIPTION_MAX = 10_000
CLOSED_STATES = ("done", "cancelled")


@dataclass
class SyncResult:
    """Counts of one pass; ``errors`` lists per-ref lookup failures (the pass still completes)."""

    listed: int = 0
    created: int = 0
    retitled: int = 0
    reopened: int = 0
    closed: int = 0
    checked: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    created_ids: list[int] = field(default_factory=list)
    closed_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listed": self.listed, "created": self.created, "retitled": self.retitled,
            "reopened": self.reopened, "closed": self.closed, "checked": self.checked,
            "unchanged": self.unchanged, "errors": list(self.errors),
            "created_ids": list(self.created_ids), "closed_ids": list(self.closed_ids),
        }

    def summary(self) -> str:
        bits = [f"{self.listed} open issue(s)"]
        for label, n in (("new", self.created), ("retitled", self.retitled), ("reopened", self.reopened), ("closed", self.closed)):
            if n:
                bits.append(f"{n} {label}")
        if self.errors:
            bits.append(f"{len(self.errors)} error(s)")
        return " · ".join(bits)


def _trim(body: str | None) -> str:
    text = (body or "").replace("\r\n", "\n").strip()
    return text[:DESCRIPTION_MAX]


def task_from_issue(conn: Any, info: IssueInfo, *, actor: str = SYNC_ACTOR) -> dict[str, Any]:
    """Create the coding task for ``info`` (title, code, inbox, description, issue link + ref)."""
    task = repo.create_task(
        conn, info.title or info.ref, actor=actor,
        code=f"{short_repo(info.repo)}#{info.number}", status="inbox", description=_trim(info.body),
    )
    repo.add_link(conn, task["id"], info.url, label=info.ref, kind="issue")
    return repo.set_issue_ref(
        conn, task["id"], provider=info.provider, repo=info.repo, number=info.number,
        url=info.url, state=info.state, actor=actor,
    )


def sync_once(conn: Any, provider: IssueProvider, *, actor: str = SYNC_ACTOR,
              cache: dict[tuple[str, str, int], IssueInfo] | None = None) -> SyncResult:
    """One reconciliation pass (see the module doc). Raises :class:`IssueProviderError`
    only when the *listing* fails — per-ref lookups degrade into ``result.errors``."""
    result = SyncResult()
    issues = provider.list_open_assigned()          # raises → nothing changes
    result.listed = len(issues)
    open_by_key = {i.key: i for i in issues}
    if cache is not None:
        cache.update(open_by_key)

    refs = {(r["provider"], r["repo"], int(r["number"])): r for r in repo.list_issue_refs(conn, provider.name)}
    ts = repo.now_iso()

    # 2 + 3 — every open assigned issue
    for key, info in open_by_key.items():
        ref = refs.get(key)
        if ref is None:
            task = task_from_issue(conn, info, actor=actor)
            result.created += 1
            result.created_ids.append(task["id"])
            logger.info("ℹ️ issues: new task #%d from %s — %s", task["id"], info.ref, info.title)
            continue
        task_id = int(ref["task_id"])
        changed = False
        if info.title and info.title != ref["task_title"]:
            repo.update_task(conn, task_id, actor=actor, title=info.title)
            result.retitled += 1
            changed = True
        if ref["state"] == "closed":
            if ref["task_status"] in CLOSED_STATES:
                repo.update_task(conn, task_id, actor=actor, status="todo")
            result.reopened += 1
            changed = True
            logger.info("ℹ️ issues: %s reopened → task #%d back to todo", info.ref, task_id)
        repo.touch_issue_ref(conn, task_id, state="open", url=info.url or None, actor=actor, ts=ts)
        if not changed:
            result.unchanged += 1

    # 4 — refs that should be open but were not listed: confirm before acting
    for key, ref in refs.items():
        if key in open_by_key or ref["state"] == "closed":
            continue
        task_id = int(ref["task_id"])
        result.checked += 1
        try:
            info = provider.get(ref["repo"], int(ref["number"]))
        except IssueProviderError as exc:
            result.errors.append(f"{ref['repo']}#{ref['number']}: {exc}")
            logger.warning("⚠️ issues: could not confirm %s#%s (%s) — left as is", ref["repo"], ref["number"], exc)
            continue
        if cache is not None:
            cache[info.key] = info
        if info.state == "closed":
            if ref["task_status"] not in CLOSED_STATES:
                repo.update_task(conn, task_id, actor=actor, status="done")
                result.closed_ids.append(task_id)
            repo.touch_issue_ref(conn, task_id, state="closed", url=info.url or None, actor=actor, ts=ts)
            result.closed += 1
            logger.info("ℹ️ issues: %s closed on the forge → task #%d done", info.ref, task_id)
        else:
            repo.touch_issue_ref(conn, task_id, state="open", url=info.url or None, actor=actor, ts=ts)
            result.unchanged += 1
    return result


class IssueSyncService:
    """The in-app scheduler + status holder (one per process, on ``app.state.issues``)."""

    def __init__(self, config: AppConfig, provider: IssueProvider | None = None, *,
                 interval_minutes: int | None = None, initial_delay: float = INITIAL_DELAY_S) -> None:
        self.provider = provider or get_provider(config)
        self.interval_minutes = max(1, int(interval_minutes or config.issues.sync_minutes or 10))
        self.initial_delay = initial_delay
        self.enabled, self.reason = self.provider.is_configured()
        self.last_sync: str | None = None
        self.last_result: SyncResult | None = None
        self.last_error: str | None = None
        self.last_error_code: str | None = None
        self.next_run: datetime | None = None
        self.cache: dict[tuple[str, str, int], IssueInfo] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if not self.enabled:
            logger.warning("⚠️ issues: sync disabled — %s", self.reason)

    # ------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "enabled": self.enabled,
            "reason": None if self.enabled else self.reason,
            "sync_minutes": self.interval_minutes,
            "last_sync": self.last_sync,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "last_error": self.last_error,
            "last_error_code": self.last_error_code,
            "next_run": self.next_run.isoformat(timespec="minutes") if self.next_run else None,
            "running": self._thread is not None and self._thread.is_alive(),
            "repos": sorted({k[1] for k in self.cache}),
        }

    def cached(self, provider: str, repo: str, number: int) -> IssueInfo | None:
        return self.cache.get((provider, repo, int(number)))

    # ---------------------------------------------------------------- run
    def run_now(self, conn: Any | None = None) -> SyncResult | None:
        """One pass now (also the thread's tick). Errors are recorded, never raised past here."""
        if not self.enabled:
            return None
        with self._lock:
            own = conn is None
            c = conn or connect()
            try:
                result = sync_once(c, self.provider, cache=self.cache)
            except IssueProviderError as exc:
                self.last_error = str(exc)
                self.last_error_code = exc.code
                logger.error("❌ issues: sync failed (%s): %s", exc.code, exc)
                return None
            except Exception as exc:  # noqa: BLE001 — a bug in a pass is a status, not a crash of the app
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_error_code = "error"
                logger.exception("❌ issues: sync crashed")
                return None
            finally:
                if own:
                    c.close()
            self.last_error = None
            self.last_error_code = None
            self.last_sync = repo.now_iso()
            self.last_result = result
            logger.info("✅ issues: sync — %s", result.summary())
            return result

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self.next_run = datetime.now() + timedelta(seconds=self.initial_delay)
        self._thread = threading.Thread(target=self._run, name="task-os-issues", daemon=True)
        self._thread.start()
        logger.info("ℹ️ issues: %s sync every %d min (first pass in %.0f s)", self.provider.name,
                    self.interval_minutes, self.initial_delay)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        if self._stop.wait(self.initial_delay):
            return
        while not self._stop.is_set():
            self.run_now()
            self.next_run = datetime.now() + timedelta(minutes=self.interval_minutes)
            if self._stop.wait(self.interval_minutes * 60):
                return


__all__ = ["CLOSED_STATES", "INITIAL_DELAY_S", "SYNC_ACTOR", "IssueSyncService", "SyncResult", "sync_once", "task_from_issue"]
