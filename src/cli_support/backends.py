"""The ``tasks`` CLI's two backends — the running webapp over HTTP(S), or
the database directly when the app is down. Both expose the same method set
and return the same dict shapes, so every command formats one way regardless
of the transport."""

from __future__ import annotations

import json
import logging
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from src.config import load_config

logger = logging.getLogger(__name__)

#: What either backend reports for a status fact it could not establish.
#: ``GET /api/status`` already ships this literal for ``auth.client`` when the
#: middleware cannot classify a request, so it is this repo's existing word for
#: "not confirmed" rather than a new one — see :meth:`LocalBackend.status`.
UNKNOWN = "unknown"


class CliError(Exception):
    """A user-facing failure: message + optional structured detail."""

    def __init__(self, message: str, code: str = "error", detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


# Where the
# offline backend genuinely cannot establish a value the key is still present,
# carrying ``UNKNOWN`` — the shape never varies, only the confidence does.

Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _tls_context(base: str) -> ssl.SSLContext | None:
    """HTTPS to loopback skips certificate verification (hostname included): the served leaf names the
    tailnet host (``<host>.ts.net``), never ``127.0.0.1``, and loopback is
    already the owner (``src/auth.py``) — the same exception the tray's own
    probe makes (``WebappManager.is_reachable``, #259). Any other host is
    verified as usual (``None`` = urllib's default context)."""
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "https" or (parts.hostname or "") not in _LOOPBACK_HOSTS:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _urllib_transport(base: str, actor: str | None) -> Transport:
    tls = _tls_context(base)

    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if actor:
            req.add_header("X-Actor", actor)
        try:
            with urllib.request.urlopen(req, timeout=15, context=tls) as res:
                raw = res.read().decode("utf-8")
                return res.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"error": {"code": "http_error", "message": raw or str(exc)}}
        except (urllib.error.URLError, OSError) as exc:
            raise CliError(f"cannot reach {base}: {exc}", code="unreachable") from exc

    return send


class HttpBackend:
    """Talks to the running webapp; ``transport`` is injectable for tests."""

    name = "http"

    def __init__(self, base: str, actor: str | None = None, transport: Transport | None = None):
        self.base = base.rstrip("/")
        self.actor = actor
        self._send = transport or _urllib_transport(self.base, actor)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        status, payload = self._send(method, path, body)
        if status >= 400:
            err = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
            raise CliError(
                err.get("message") or f"HTTP {status}", code=err.get("code", "http_error"),
                detail=err.get("detail"),
            )
        return payload

    def add(self, **fields: Any) -> dict[str, Any]:
        return self._call("POST", "/api/tasks", {**fields, "actor": self.actor})

    def ls(self, **filters: Any) -> list[dict[str, Any]]:
        params = {k: v for k, v in filters.items() if v is not None}
        if params.pop("deferred", False):
            # `deferred` rides the `status` list on the wire — the same URL
            # vocabulary the web app's filter card shares, so there is
            # one spelling of "show me the sleeping ones", not two.
            picked = [s for s in str(params.get("status") or "").split(",") if s]
            params["status"] = ",".join([*picked, "deferred"])
        if params.pop("blocked", False):
            # same trick as `deferred`, its own pseudo-value
            picked = [s for s in str(params.get("status") or "").split(",") if s]
            params["status"] = ",".join([*picked, "blocked"])
        query = urllib.parse.urlencode(params)
        return self._call("GET", "/api/tasks" + (f"?{query}" if query else ""))["items"]

    def show(self, task_id: int) -> dict[str, Any]:
        return self._call("GET", f"/api/tasks/{task_id}")

    def tree(self, root: int | None) -> list[dict[str, Any]]:
        q = f"?root={root}" if root is not None else ""
        return self._call("GET", f"/api/tasks/tree{q}")["items"]

    def comment(self, task_id: int, text: str) -> dict[str, Any]:
        body = {"body": text, "origin": "cli", "author": self.actor}
        return self._call("POST", f"/api/tasks/{task_id}/comments", body)

    def due(self, task_id: int, due: str | None) -> dict[str, Any]:
        return self._call("PATCH", f"/api/tasks/{task_id}", {"due": due, "actor": self.actor})

    def update(self, task_id: int, **fields: Any) -> dict[str, Any]:
        return self._call("PATCH", f"/api/tasks/{task_id}", {**fields, "actor": self.actor})

    def link(self, task_id: int, url: str, label: str | None, kind: str | None) -> dict[str, Any]:
        body = {"url": url, "label": label, "kind": kind}
        return self._call("POST", f"/api/tasks/{task_id}/links", body)

    def starts(self, task_id: int, starts: str | None) -> dict[str, Any]:
        return self._call("PATCH", f"/api/tasks/{task_id}", {"starts": starts, "actor": self.actor})

    def done(self, task_id: int) -> dict[str, Any]:
        return self._call("POST", f"/api/tasks/{task_id}/done", {"actor": self.actor})

    def delete(self, task_id: int) -> dict[str, Any]:
        return self._call("DELETE", f"/api/tasks/{task_id}")

    def move(self, task_id: int, parent_id: int | None) -> dict[str, Any]:
        body = {"parent_id": parent_id, "actor": self.actor}
        return self._call("POST", f"/api/tasks/{task_id}/move", body)

    def block(self, task_id: int, blocker_id: int) -> dict[str, Any]:
        body = {"blocker_id": blocker_id, "actor": self.actor}
        return self._call("POST", f"/api/tasks/{task_id}/blockers", body)

    def unblock(self, task_id: int, blocker_id: int) -> dict[str, Any]:
        return self._call("DELETE", f"/api/tasks/{task_id}/blockers/{blocker_id}")

    def search(self, q: str, kinds: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q}
        if kinds:
            params["kinds"] = ",".join(kinds)
        return self._call("GET", "/api/search?" + urllib.parse.urlencode(params))

    def people(self) -> list[dict[str, Any]]:
        return self._call("GET", "/api/people")["items"]

    def mirror_export(self) -> dict[str, Any]:
        return self._call("POST", "/api/mirror/export")

    def mirror_import(self) -> dict[str, Any]:
        return self._call("POST", "/api/mirror/import")

    def status(self) -> dict[str, Any]:
        return self._call("GET", "/api/status")

    def backup(self) -> dict[str, Any]:
        return self._call("POST", "/api/backup")

    def issues_status(self) -> dict[str, Any]:
        return self._call("GET", "/api/issues/status")

    def issues_sync(self) -> dict[str, Any]:
        return self._call("POST", "/api/issues/sync")

    def issue_create(self, task_id: int, repo: str) -> dict[str, Any]:
        return self._call("POST", f"/api/tasks/{task_id}/issue", {"repo": repo, "actor": self.actor})

    def folders_reindex(self) -> dict[str, Any]:
        return self._call("POST", "/api/folders/reindex")

    def folders_search(self, q: str) -> dict[str, Any]:
        return self._call("GET", "/api/folders/search?" + urllib.parse.urlencode({"q": q}))

    def triage(self) -> list[dict[str, Any]]:
        return self._call("POST", "/api/ai/triage", {})["items"]

    def accept_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        return self._call("POST", f"/api/ai/suggestions/{suggestion_id}/accept")

    def reject_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        return self._call("POST", f"/api/ai/suggestions/{suggestion_id}/reject")


class LocalBackend:
    """Opens the database directly — the app-down path."""

    name = "local"

    def __init__(self, actor: str | None = None):
        from src import tasks_repo
        from src.db import connect, init_db

        self.actor = actor
        self._repo = tasks_repo
        # who an `owner` may name, and who a NULL one is — as the app's lifespan does
        tasks_repo.set_members([p.id for p in load_config().people])
        init_db()
        self.conn: sqlite3.Connection = connect()
        # Writes made here bypass the app's debounced exporter, so collect the
        # touched ids and mirror them synchronously in finish().
        self._touched: set[int] = set()
        self._repo.add_write_listener(self._on_write)
        self._mirror: Any = None
        self._ai: Any = None

    def _on_write(self, ids: list[int]) -> None:
        self._touched.update(ids)

    def _mirror_service(self) -> Any:
        if self._mirror is None:
            from src.mirror import Mirror

            self._mirror = Mirror(load_config())
        return self._mirror

    def finish(self) -> int:
        """Export the tasks this command touched (when the mirror is configured); returns the count."""
        self._repo.remove_write_listener(self._on_write)
        if not self._touched:
            return 0
        mirror = self._mirror_service()
        if not mirror.enabled:
            return 0
        try:
            return mirror.export_ids(self.conn, sorted(self._touched))
        except Exception as exc:  # noqa: BLE001 — the command already succeeded; the app's next full export catches up
            logger.warning("⚠️ mirror export after the command failed: %s", exc)
            return 0

    def _wrap(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(self.conn, *args, **kwargs)
        except self._repo.RepoError as exc:
            raise CliError(str(exc), code=exc.code) from exc

    def add(self, **fields: Any) -> dict[str, Any]:
        title = fields.pop("title")
        return self._wrap(self._repo.create_task, title, actor=self.actor, **fields)

    def ls(self, **filters: Any) -> list[dict[str, Any]]:
        status = filters.get("status")
        return self._wrap(
            self._repo.list_tasks,
            status=[s for s in status.split(",")] if status else None,
            parent_id=filters.get("parent"),
            project=filters.get("project"),
            due=filters.get("due"),
            type=filters.get("type"),
            person_id=filters.get("person"),
            owner=[o for o in filters["owner"].split(",") if o] if filters.get("owner") else None,
            q=filters.get("q"),
            include_closed=bool(filters.get("include_closed")),
            updated_before=filters.get("updated_before"),
            done_from=filters.get("done_from"),
            done_to=filters.get("done_to"),
            # None = follow include_closed, so `ls --status all` means all
            deferred="only" if filters.get("deferred") else None,
            blocked="only" if filters.get("blocked") else None,
        )

    def show(self, task_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.get_task, task_id)

    def tree(self, root: int | None) -> list[dict[str, Any]]:
        return self._wrap(self._repo.tree, root)

    def comment(self, task_id: int, text: str) -> dict[str, Any]:
        return self._wrap(self._repo.add_comment, task_id, text, author=self.actor, origin="cli")

    def due(self, task_id: int, due: str | None) -> dict[str, Any]:
        return self._wrap(self._repo.set_due, task_id, due, actor=self.actor)

    def update(self, task_id: int, **fields: Any) -> dict[str, Any]:
        return self._wrap(self._repo.update_task, task_id, actor=self.actor, **fields)

    def link(self, task_id: int, url: str, label: str | None, kind: str | None) -> dict[str, Any]:
        return self._wrap(self._repo.add_link, task_id, url, label=label, kind=kind)

    def starts(self, task_id: int, starts: str | None) -> dict[str, Any]:
        return self._wrap(self._repo.set_starts, task_id, starts, actor=self.actor)

    def done(self, task_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.done, task_id, actor=self.actor)

    def delete(self, task_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.delete_task, task_id)

    def move(self, task_id: int, parent_id: int | None) -> dict[str, Any]:
        return self._wrap(self._repo.move, task_id, parent_id, actor=self.actor)

    def block(self, task_id: int, blocker_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.add_blocker, task_id, blocker_id, actor=self.actor)

    def unblock(self, task_id: int, blocker_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.remove_blocker, task_id, blocker_id, actor=self.actor)

    def search(self, q: str, kinds: list[str] | None = None) -> dict[str, Any]:
        # The same four adapters the webapp runs, built here over this
        # process's config: the folder index loaded from its file (no scan),
        # the issue service cold (local refs only — the sync's cache lives in
        # the app), the email index read-only.
        from src.folder_index import FolderIndexService
        from src.issue_sync import IssueSyncService
        from src.search import build_federated

        config = load_config()
        folders = FolderIndexService(config)
        if folders.enabled:
            try:
                folders.load()
            except OSError:
                pass
        return build_federated(config, folders=folders, issues=IssueSyncService(config)).search(q, kinds=kinds)

    def people(self) -> list[dict[str, Any]]:
        return self._wrap(self._repo.list_people)

    def _ai_client(self) -> Any:
        if self._ai is None:
            from src.ai import AIClient

            self._ai = AIClient(load_config())
        return self._ai

    def triage(self) -> list[dict[str, Any]]:
        from src.ai import AIError, generate_suggestions

        try:
            return generate_suggestions(self.conn, self._ai_client())
        except AIError as exc:
            raise CliError(str(exc), code=exc.code, detail=exc.detail) from exc

    def accept_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        from src.ai import accept_suggestion

        return self._wrap(accept_suggestion, suggestion_id)

    def reject_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        from src.ai import reject_suggestion

        return self._wrap(reject_suggestion, suggestion_id)

    def mirror_export(self) -> dict[str, Any]:
        mirror = self._mirror_service()
        if not mirror.enabled:
            raise CliError(mirror.reason, code="mirror_disabled")
        return mirror.export_all(self.conn)

    def mirror_import(self) -> dict[str, Any]:
        mirror = self._mirror_service()
        if not mirror.enabled:
            raise CliError(mirror.reason, code="mirror_disabled")
        return mirror.import_tick(self.conn)

    def status(self) -> dict[str, Any]:
        """The full ``GET /api/status`` key set, assembled offline.

        Two of those keys describe the **request** rather than the install:
        ``https`` is the scheme the caller's connection arrived on, and
        ``auth.client`` is how ``AuthMiddleware`` classified that connection.
        With the app down there is no connection, so both are reported as
        :data:`UNKNOWN` — never omitted (a missing key reads to a consumer as
        "plain HTTP", which is an answer this process did not establish) and
        never inferred from the config (``src/certs.py`` knows what the *next*
        webapp spawn would bind; that is not what a client actually got).

        Everything else the API returns is a property of the install, not of
        the request, so it is answered for real here: the auth config, the
        four services, the voice endpoint's reachability, and — from this
        PC's filesystem and registry — the opener registration and the
        placeholder map.
        """
        from src import opener
        from src.ai import AIClient
        from src.archive_batch import ArchiveBatchService
        from src.backup import BackupScheduler
        from src.calendar_lane import CalendarService
        from src.email_capture import EmailCaptureService
        from src.enrich import EnrichClient
        from src.folder_index import FolderIndexService
        from src.voice import VoiceClient

        config = load_config()
        folders = FolderIndexService(config)
        if folders.enabled:
            try:
                folders.load()
            except OSError:
                pass
        placeholders = dict(config.placeholders)
        return {
            "https": UNKNOWN,
            "auth": {
                "enabled": config.auth.enabled,
                "password": bool(config.auth.password_hash),
                "client": UNKNOWN,
            },
            "mirror": self._mirror_service().status(self.conn),
            "backup": BackupScheduler(config).status(),
            "folders": folders.status(),
            # Built but never started — offline there is no poller thread, so
            # `running` is False and `next_run` None. Both are facts about this
            # process, not guesses; the enabled/reason pair (does this install
            # have a flag-carrying index?) is what the caller actually asked.
            "capture": EmailCaptureService(config).status(),
            # Reachability of the whisper endpoint *from this PC* is a fact
            # this process can establish with or without the app — the
            # same TCP probe the webapp answers with.
            "voice": VoiceClient(config).status(),
            # Same fact, same shape, for the text model: a TCP probe
            # this process can run whether or not the app is up.
            "enrich": EnrichClient(config).status(),
            "ai": AIClient(config).status(),
            # Whether this install can drive the archiver, and what the last run
            # did — both read off the config and this database, so the answer is
            # the same with the app up or down. Nothing is spawned here.
            "archive": ArchiveBatchService(config).status(self.conn),
            # The calendar is an install fact too: the address is in the
            # config and the fetch runs from this PC, bounded by its timeout.
            "calendar": CalendarService(config).status(),
            "opener": opener.status(placeholders),
            "placeholders": placeholders,
        }

    def backup(self) -> dict[str, Any]:
        from src.backup import BackupScheduler

        scheduler = BackupScheduler(load_config())
        if not scheduler.enabled:
            raise CliError(scheduler.reason, code="backup_disabled")
        target = scheduler.run_now()
        if target is None:
            raise CliError(scheduler.last_error or "backup failed", code="backup_failed")
        return {"file": target.name, "dir": str(target.parent), "path": str(target)}

    def _issue_service(self) -> Any:
        from src.issue_sync import IssueSyncService

        return IssueSyncService(load_config())

    def issues_status(self) -> dict[str, Any]:
        service = self._issue_service()
        body = service.status()
        body["repos"] = sorted({r["repo"] for r in self._repo.list_issue_refs(self.conn)})
        return body

    def issues_sync(self) -> dict[str, Any]:
        service = self._issue_service()
        if not service.enabled:
            raise CliError(service.reason, code="issues_disabled")
        result = service.run_now(self.conn)
        if result is None:
            raise CliError(service.last_error or "sync failed", code="provider_error")
        return result.to_dict()

    def issue_create(self, task_id: int, repo: str) -> dict[str, Any]:
        """The same workflow the route runs — ``src.issue_sync.issue_from_task``
        (issue #35). ``_wrap`` turns its repo-family errors (already_linked,
        issues_disabled, validation, not_found) into the CLI's dialect; the
        provider error is mapped here, as the route maps it to its 502."""
        from src.issue_sync import issue_from_task
        from src.issues import IssueProviderError

        try:
            return self._wrap(issue_from_task, task_id, repo,
                              service=self._issue_service(), actor=self.actor)
        except IssueProviderError as exc:
            raise CliError(str(exc), code="provider_error") from exc

    def _folders(self) -> Any:
        from src.folder_index import FolderIndexService

        svc = FolderIndexService(load_config())
        if not svc.enabled:
            raise CliError(svc.reason, code="folders_disabled")
        return svc

    def folders_reindex(self) -> dict[str, Any]:
        return self._folders().reindex()

    def folders_search(self, q: str) -> dict[str, Any]:
        svc = self._folders()
        svc.load()
        items = svc.search(q)
        return {"q": q, "items": items, "count": len(items), "indexing": False, "entries": svc.status()["entries"]}
