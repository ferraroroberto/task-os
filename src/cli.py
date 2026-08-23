"""``tasks`` — the terminal / scripting / LLM surface of task-os.

    tasks add "Renew passport" --due fri [--parent N] [--priority high]
              [--recurrence weekly] [--person "Sam"] [--desc "..."]
    tasks ls [--status todo,doing|open|all] [--project N] [--due today|week|overdue]
    tasks show N
    tasks tree [N]
    tasks comment N "text"
    tasks due N <date>          natural (fri, next friday, in 2 weeks) or ISO; "none" clears
    tasks done N
    tasks move N --parent M     (--parent root → top level)
    tasks search "q" [--kind tasks|folders|emails|issues]   federated: tasks · folders · emails · issues
    tasks people
    tasks mirror export|import|status   markdown mirror: full export · one watcher pass · status
    tasks backup                        copy the database to mirror.backup_dir now
    tasks issues sync|status            issue provider: one sync pass now · status (default)
    tasks issue create N --repo owner/name   open an issue from task N and link it (→ coding)
    tasks folders reindex|status|search "q"   the folder index (search.folder_roots)

Every command takes ``--json`` for machine-readable output (the same shapes
the REST API returns — a fact only a live request can settle, such as
``mirror status``'s ``https``, comes back as the string ``"unknown"`` on the
app-down path rather than being omitted or guessed). Talks to the running
server over HTTP when it answers
(``http://127.0.0.1:<config port>``, override with ``--server URL`` /
``TASKOS_URL``); otherwise — app down — it opens the database directly, so
the CLI works either way. ``--local`` forces the direct path. ``--actor``
names who is acting (activity / comment author); default = the configured
first team member.

Exit codes: 0 ok · 1 error (message on stderr, or the JSON error envelope
with ``--json``) · 2 usage.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from src.config import load_config
from src.dates import DateParseError, parse_date
from src.schema import RECURRENCES, TASK_PRIORITIES, TASK_STATUSES

logger = logging.getLogger(__name__)

SERVER_ENV = "TASKOS_URL"
PROBE_TIMEOUT_S = 0.8

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


# ------------------------------------------------------------------ backends
#
# Both backends expose the same method set and return the same dict shapes,
# so every command formats one way regardless of the transport. Where the
# offline backend genuinely cannot establish a value the key is still present,
# carrying ``UNKNOWN`` — the shape never varies, only the confidence does.

Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]


def _urllib_transport(base: str, actor: str | None) -> Transport:
    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if actor:
            req.add_header("X-Actor", actor)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
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

    def done(self, task_id: int) -> dict[str, Any]:
        return self._call("POST", f"/api/tasks/{task_id}/done", {"actor": self.actor})

    def move(self, task_id: int, parent_id: int | None) -> dict[str, Any]:
        body = {"parent_id": parent_id, "actor": self.actor}
        return self._call("POST", f"/api/tasks/{task_id}/move", body)

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


class LocalBackend:
    """Opens the database directly — the app-down path."""

    name = "local"

    def __init__(self, actor: str | None = None):
        from src import tasks_repo
        from src.db import connect, init_db

        self.actor = actor
        self._repo = tasks_repo
        init_db()
        self.conn: sqlite3.Connection = connect()
        # Writes made here bypass the app's debounced exporter, so collect the
        # touched ids and mirror them synchronously in finish().
        self._touched: set[int] = set()
        self._repo.add_write_listener(self._on_write)
        self._mirror: Any = None

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
            q=filters.get("q"),
            include_closed=bool(filters.get("include_closed")),
        )

    def show(self, task_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.get_task, task_id)

    def tree(self, root: int | None) -> list[dict[str, Any]]:
        return self._wrap(self._repo.tree, root)

    def comment(self, task_id: int, text: str) -> dict[str, Any]:
        return self._wrap(self._repo.add_comment, task_id, text, author=self.actor, origin="cli")

    def due(self, task_id: int, due: str | None) -> dict[str, Any]:
        return self._wrap(self._repo.set_due, task_id, due, actor=self.actor)

    def done(self, task_id: int) -> dict[str, Any]:
        return self._wrap(self._repo.done, task_id, actor=self.actor)

    def move(self, task_id: int, parent_id: int | None) -> dict[str, Any]:
        return self._wrap(self._repo.move, task_id, parent_id, actor=self.actor)

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
        three services, and — from this PC's filesystem and registry — the
        opener registration and the placeholder map.
        """
        from src import opener
        from src.backup import BackupScheduler
        from src.folder_index import FolderIndexService

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
            "mirror": self._mirror_service().status(),
            "backup": BackupScheduler(config).status(),
            "folders": folders.status(),
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


def server_answers(base: str, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """One short ``/healthz`` probe — is the app up?"""
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=timeout) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError):
        return False


def pick_backend(args: argparse.Namespace) -> HttpBackend | LocalBackend:
    config = load_config()
    actor = args.actor or (config.team.people[0] if config.team.people else None)
    if args.local:
        return LocalBackend(actor)
    base = args.server or os.environ.get(SERVER_ENV, "").strip() or f"http://127.0.0.1:{config.port}"
    if server_answers(base):
        return HttpBackend(base, actor)
    if args.server or os.environ.get(SERVER_ENV):
        raise CliError(f"nothing answers {base}/healthz (drop --server / {SERVER_ENV} to use the database directly)")
    return LocalBackend(actor)


# ---------------------------------------------------------------- formatting


def _fmt_task_line(t: dict[str, Any], indent: int = 0) -> str:
    bits = [f"#{t['id']}", t["title"]]
    tail = []
    if t.get("status") and t["status"] != "inbox":
        tail.append(t["status"])
    if t.get("priority") and t["priority"] != "none":
        tail.append(f"prio {t['priority']}")
    if t.get("due"):
        tail.append(f"due {t['due']}")
    if t.get("recurrence"):
        tail.append(f"every {t['recurrence']}")
    if t.get("type") == "coding" and t.get("issue_ref"):
        tail.append(f"{t['issue_ref']['repo']}#{t['issue_ref']['number']}")
    if t.get("person"):
        tail.append(f"@{t['person']['name']}")
    line = "  " * indent + "  ".join(bits)
    if tail:
        line += "  (" + ", ".join(tail) + ")"
    return line


def _crumb(t: dict[str, Any]) -> str:
    return " › ".join(c["title"] for c in t.get("breadcrumb") or [])


def fmt_ls(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(no tasks)"
    rows = []
    for t in items:
        rows.append((
            f"#{t['id']}", t["status"], t["priority"] if t["priority"] != "none" else "",
            t.get("due") or "", t["title"] + (f"  ({t['child_count']})" if t.get("is_project") else ""),
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    out = []
    for r in rows:
        out.append("  ".join(r[i].ljust(widths[i]) for i in range(4)) + "  " + r[4])
    return "\n".join(out)


def fmt_show(t: dict[str, Any]) -> str:
    lines = [_fmt_task_line(t)]
    crumb = _crumb(t)
    if crumb:
        lines.append(f"  in: {crumb}")
    lines.append(f"  type {t['type']} · status {t['status']} · priority {t['priority']} · due {t.get('due') or '-'}"
                 + (f" · every {t['recurrence']}" if t.get("recurrence") else ""))
    if t.get("description"):
        lines.append(f"  {t['description']}")
    if t.get("folder_ref"):
        lines.append(f"  folder: {t['folder_ref']}")
    if t.get("next_action"):
        lines.append(f"  next: {t['next_action']}")
    lines.append(f"  created {t['created_at']} by {t.get('created_by') or '-'} · updated {t['updated_at']}"
                 + (f" · done {t['done_at']}" if t.get("done_at") else ""))
    if t.get("children"):
        lines.append("  children:")
        lines.extend(_fmt_task_line(c, indent=2) for c in t["children"])
    if t.get("links"):
        lines.append("  links:")
        lines.extend(f"    [{lk['kind']}] {lk.get('label') or lk['url']}  {lk['url']}" for lk in t["links"])
    if t.get("comments"):
        lines.append("  comments:")
        lines.extend(f"    {c['ts']}  {c.get('author') or '-'} ({c['origin']}): {c['body']}" for c in t["comments"])
    if t.get("activity"):
        lines.append("  activity:")
        for a in t["activity"]:
            lines.append(f"    {a['ts']}  {a.get('actor') or '-'}  {a['field']}: {a.get('old_value') if a.get('old_value') is not None else '∅'} → {a.get('new_value') if a.get('new_value') is not None else '∅'}")
    return "\n".join(lines)


def fmt_tree(nodes: list[dict[str, Any]], depth: int = 0) -> list[str]:
    out: list[str] = []
    for n in nodes:
        out.append(_fmt_task_line(n, indent=depth))
        out.extend(fmt_tree(n.get("children") or [], depth + 1))
    return out


def fmt_search(result: dict[str, Any]) -> str:
    """The federated result as text — one block per kind; an unconfigured or
    errored group says so on its header line (never a silent blank)."""
    out: list[str] = []
    for g in result.get("groups") or []:
        kind = g["kind"]
        if g.get("skipped"):
            continue
        if not g.get("configured"):
            out.append(f"{kind}: not configured — {g.get('reason') or 'unknown'}")
            continue
        head = f"{kind} ({g.get('count', 0)} · {g.get('took_ms', 0)} ms)"
        if g.get("error"):
            head += f"  error: {g['error']}"
        if g.get("note"):
            head += f"  — {g['note']}"
        out.append(head)
        for h in g.get("hits") or []:
            if kind == "tasks":
                lead = f"#{h['task_id']}  {h['title']}"
            elif kind == "issues":
                lead = f"{h['ref']}  {h['title']}"
            else:
                lead = h["title"]
            sub = f"  — {h['subtitle']}" if h.get("subtitle") else ""
            out.append(f"  {lead}{sub}")
            snippet = h.get("snippet") or ""
            if snippet and snippet != h.get("title"):
                where = f"{h['matched_in']}: " if h.get("matched_in") else ""
                out.append(f"      {where}{snippet}")
            if kind in ("folders", "emails"):
                out.append(f"      {h['ref']}")
    return "\n".join(out) if out else "(no hits)"


def fmt_people(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(no people)"
    return "\n".join(f"#{p['id']}  {p['name']}" + (f"  <{p['email']}>" if p.get("email") else "")
                     + f"  ({p.get('open_tasks', 0)} open)" for p in items)


def fmt_issues_status(st: dict[str, Any]) -> str:
    provider = st.get("provider") or "none"
    if not st.get("enabled"):
        return f"issues   {provider}: not configured — {st.get('reason') or 'unknown'}"
    r = st.get("last_result") or {}
    lines = [f"issues   {provider} · every {st.get('sync_minutes')} min · last sync {st.get('last_sync') or '-'}"
             + (f" · next {st.get('next_run')}" if st.get("next_run") else "")]
    if st.get("last_error"):
        lines.append(f"         last error ({st.get('last_error_code') or 'error'}): {st['last_error']}")
    if r:
        lines.append(f"         last result: {r.get('listed', 0)} open issue(s) · {r.get('created', 0)} new"
                     f" · {r.get('retitled', 0)} retitled · {r.get('reopened', 0)} reopened · {r.get('closed', 0)} closed"
                     + (f" · {len(r.get('errors') or [])} error(s)" if r.get("errors") else ""))
    if st.get("repos"):
        lines.append(f"         repos: {', '.join(st['repos'])}")
    return "\n".join(lines)


def fmt_status(status: dict[str, Any]) -> str:
    m = status.get("mirror") or {}
    b = status.get("backup") or {}
    lines = []
    if m.get("enabled"):
        lines.append(f"mirror   enabled · {m.get('dir')} · {m.get('files')} file(s)"
                     f" · last export {m.get('last_export') or '-'} · last import {m.get('last_import') or '-'}"
                     f" · errors {m.get('errors', 0)}"
                     + (f" ({', '.join(m.get('error_files') or [])})" if m.get("error_files") else "")
                     + (" · watching" if m.get("watching") else ""))
    else:
        lines.append(f"mirror   not configured — {m.get('reason') or 'unknown'}")
    if b.get("enabled"):
        lines.append(f"backup   enabled · {b.get('dir')} · last {b.get('last_file') or '-'}"
                     f" · next {b.get('next_run') or '(app not running)'}"
                     + (f" · last error {b['last_error']}" if b.get("last_error") else ""))
    else:
        lines.append(f"backup   not configured — {b.get('reason') or 'unknown'}")
    return "\n".join(lines)


def fmt_folders_status(f: dict[str, Any]) -> str:
    if not f.get("enabled"):
        return f"folders  not configured — {f.get('reason') or 'unknown'}"
    roots = ", ".join(
        f"{r.get('ref')} → {r.get('path')}" + ("" if r.get("exists") else f" ({r.get('error') or 'missing'})")
        for r in f.get("roots") or []
    )
    return (f"folders  {f.get('entries', 0)} folder(s) · roots {roots} · last indexed {f.get('last_indexed') or '-'}"
            + (" · indexing now" if f.get("indexing") else "")
            + (" · stale (>24 h)" if f.get("stale") and f.get("last_indexed") else "")
            + (f" · last error {f['last_error']}" if f.get("last_error") else ""))


def fmt_folders_search(r: dict[str, Any]) -> str:
    items = r.get("items") or []
    if not items:
        return "(no folders match)" + (" — index still building" if r.get("indexing") else "")
    return "\n".join(f"{i['ref']}\n    {i['path']}" for i in items)


# ------------------------------------------------------------------ commands


def _parse_due(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        d = parse_date(text)
    except DateParseError as exc:
        raise CliError(str(exc), code="bad_date") from exc
    return d.isoformat() if d else None


def _parent_arg(text: str | None) -> int | None:
    if text is None or text.lower() in ("root", "none", "null", "-"):
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise CliError(f"--parent expects a task id or 'root' (got {text!r})", code="usage") from exc


def _resolve_person(backend: HttpBackend | LocalBackend, text: str | None) -> int | None:
    if text is None:
        return None
    if text.isdigit():
        return int(text)
    matches = [p for p in backend.people() if p["name"].lower() == text.strip().lower()]
    if len(matches) != 1:
        raise CliError(f"person {text!r} not found (tasks people lists them)", code="not_found")
    return int(matches[0]["id"])


def run(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    """Execute one command → (json payload, human text)."""
    cmd = args.command
    if cmd == "add":
        fields: dict[str, Any] = {"title": args.title}
        if args.parent is not None:
            fields["parent_id"] = _parent_arg(args.parent)
        if args.due is not None:
            fields["due"] = _parse_due(args.due)
        if args.priority:
            fields["priority"] = args.priority
        if args.recurrence:
            fields["recurrence"] = args.recurrence
        if args.person:
            fields["person_id"] = _resolve_person(backend, args.person)
        if args.desc:
            fields["description"] = args.desc
        t = backend.add(**fields)
        return t, f"added {_fmt_task_line(t)}"
    if cmd == "ls":
        filters: dict[str, Any] = {}
        if args.status:
            if args.status == "all":
                filters["include_closed"] = True
            else:
                filters["status"] = args.status
        if args.project is not None:
            filters["project"] = args.project
        if args.due:
            filters["due"] = args.due
        if args.person:
            filters["person"] = _resolve_person(backend, args.person)
        items = backend.ls(**filters)
        return items, fmt_ls(items)
    if cmd == "show":
        t = backend.show(args.id)
        return t, fmt_show(t)
    if cmd == "tree":
        nodes = backend.tree(args.id)
        return nodes, "\n".join(fmt_tree(nodes)) or "(no tasks)"
    if cmd == "comment":
        c = backend.comment(args.id, args.text)
        return c, f"commented on #{args.id}: {c['body']}"
    if cmd == "due":
        t = backend.due(args.id, _parse_due(args.date))
        return t, f"#{t['id']} due → {t.get('due') or 'none'}"
    if cmd == "done":
        t = backend.done(args.id)
        if t.get("recurrence"):
            return t, f"#{t['id']} done — recurring {t['recurrence']}, next due {t['due']}"
        return t, f"#{t['id']} done"
    if cmd == "move":
        t = backend.move(args.id, _parent_arg(args.parent))
        where = _crumb(t) or "top level"
        return t, f"#{t['id']} moved → {where}"
    if cmd == "search":
        kinds = [args.kind] if getattr(args, "kind", None) else None
        result = backend.search(args.query, kinds)
        return result, fmt_search(result)
    if cmd == "people":
        items = backend.people()
        return items, fmt_people(items)
    if cmd == "mirror":
        if args.action == "export":
            r = backend.mirror_export()
            return r, f"mirror: {r['tasks']} task(s) → {r['written']} written, {r['removed']} removed"
        if args.action == "import":
            r = backend.mirror_import()
            imported = r.get("imported") or []
            errors = r.get("errors") or []
            detail = "".join(
                f"\n  {i['path']}: applied {list(i['applied']) or '-'} · {i['comments_added']} comment(s)"
                + (f" · conflicts {i['conflicts']}" if i.get("conflicts") else "")
                + (f" · rejected {i['rejected']}" if i.get("rejected") else "")
                for i in imported
            ) + "".join(f"\n  {e['path']}: skipped — {e['error']}" for e in errors)
            return r, (f"mirror: checked {r.get('checked', 0)} file(s), imported {len(imported)}, "
                       f"skipped {len(errors)}" + detail)
        r = backend.status()
        return r, fmt_status(r)
    if cmd == "backup":
        r = backend.backup()
        return r, f"backup written: {r['path']}"
    if cmd == "issues":
        if args.action == "sync":
            r = backend.issues_sync()
            ids = "".join(f"\n  new: #{i}" for i in r.get("created_ids") or [])
            ids += "".join(f"\n  done: #{i}" for i in r.get("closed_ids") or [])
            errs = "".join(f"\n  error: {e}" for e in r.get("errors") or [])
            return r, (f"issues: {r.get('listed', 0)} open issue(s) · {r.get('created', 0)} new"
                       f" · {r.get('retitled', 0)} retitled · {r.get('reopened', 0)} reopened"
                       f" · {r.get('closed', 0)} closed" + ids + errs)
        r = backend.issues_status()
        return r, fmt_issues_status(r)
    if cmd == "issue":
        t = backend.issue_create(args.id, args.repo)
        ref = t.get("issue_ref") or {}
        return t, f"#{t['id']} → {ref.get('repo')}#{ref.get('number')} {ref.get('url') or ''}".rstrip()
    if cmd == "folders":
        if args.action == "reindex":
            r = backend.folders_reindex()
            return r, f"folders: {r['entries']} folder(s) indexed under {', '.join(r['roots'])} in {r['seconds']}s → {r['index_file']}"
        if args.action == "search":
            if not args.query:
                raise CliError("folders search needs a query", code="usage")
            r = backend.folders_search(args.query)
            return r, fmt_folders_search(r)
        r = backend.status()
        return r.get("folders", {}), fmt_folders_status(r.get("folders") or {})
    raise CliError(f"unknown command {cmd!r}", code="usage")


# ---------------------------------------------------------------- argparse


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output (same shapes as the REST API)")

    p = argparse.ArgumentParser(prog="tasks", description="task-os from the terminal")
    p.add_argument("--json", action="store_true", default=False, help="machine-readable output")
    p.add_argument("--actor", default=None, help="who is acting (activity / comment author)")
    p.add_argument("--server", default=None, help=f"webapp base URL (default: config port; env {SERVER_ENV})")
    p.add_argument("--local", action="store_true", help="talk to the database directly, even if the app is up")
    p.add_argument("-v", "--verbose", action="store_true", help="say which backend answered (stderr)")
    sub = p.add_subparsers(dest="command", metavar="command")

    a = sub.add_parser("add", parents=[common], help="add a task")
    a.add_argument("title")
    a.add_argument("--parent", help="parent task id (nesting)")
    a.add_argument("--due", help="today · tomorrow · fri · next friday · in 2 weeks · YYYY-MM-DD")
    a.add_argument("--priority", choices=TASK_PRIORITIES)
    a.add_argument("--recurrence", choices=RECURRENCES)
    a.add_argument("--person", help="person id or name")
    a.add_argument("--desc", help="description (markdown)")

    ls = sub.add_parser("ls", parents=[common], help="list tasks")
    ls.add_argument("--status", help=f"comma list of {','.join(TASK_STATUSES)} · open (default) · all")
    ls.add_argument("--project", type=int, help="only descendants of this task")
    ls.add_argument("--due", help="today · week · overdue · YYYY-MM-DD")
    ls.add_argument("--person", help="person id or name")

    s = sub.add_parser("show", parents=[common], help="task detail with comments + activity")
    s.add_argument("id", type=int)

    t = sub.add_parser("tree", parents=[common], help="nested view")
    t.add_argument("id", type=int, nargs="?", help="root task (default: everything)")

    c = sub.add_parser("comment", parents=[common], help="add a comment")
    c.add_argument("id", type=int)
    c.add_argument("text")

    d = sub.add_parser("due", parents=[common], help="set the due date")
    d.add_argument("id", type=int)
    d.add_argument("date", help="natural or ISO; 'none' clears")

    dn = sub.add_parser("done", parents=[common], help="complete (recurring tasks roll forward)")
    dn.add_argument("id", type=int)

    m = sub.add_parser("move", parents=[common], help="re-parent")
    m.add_argument("id", type=int)
    m.add_argument("--parent", required=True, help="new parent id, or 'root'")

    se = sub.add_parser("search", parents=[common], help="federated search: tasks · folders · emails · issues")
    se.add_argument("query")
    se.add_argument("--kind", choices=("tasks", "folders", "emails", "issues"), default=None,
                    help="one index only (default: all four)")

    sub.add_parser("people", parents=[common], help="list people")

    mi = sub.add_parser("mirror", parents=[common], help="markdown mirror: export · import · status")
    mi.add_argument("action", choices=("export", "import", "status"), nargs="?", default="status",
                    help="export = every task to mirror.dir now · import = one watcher pass · status (default)")

    sub.add_parser("backup", parents=[common],
                   help="copy the database to mirror.backup_dir now (tasks-YYYYMMDD.db)")

    iss = sub.add_parser("issues", parents=[common], help="issue provider: sync now · status")
    iss.add_argument("action", choices=("sync", "status"), nargs="?", default="status",
                     help="sync = one reconciliation pass now · status (default)")

    ic = sub.add_parser("issue", parents=[common], help="issue actions on one task")
    ic.add_argument("action", choices=("create",), help="create = open an issue from the task and link it")
    ic.add_argument("id", type=int)
    ic.add_argument("--repo", required=True, help="owner/name to open the issue in")

    fo = sub.add_parser("folders", parents=[common], help="folder index: reindex · status · search")
    fo.add_argument("action", choices=("reindex", "status", "search"), nargs="?", default="status",
                    help="reindex = rescan search.folder_roots now · search = substring AND over the index · status (default)")
    fo.add_argument("query", nargs="?", help="search terms (for: search)")
    return p


def main(argv: list[str] | None = None, backend: HttpBackend | LocalBackend | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    as_json = bool(getattr(args, "json", False))
    try:
        be = backend or pick_backend(args)
        if args.verbose:
            if isinstance(be, HttpBackend):
                where = be.base
            else:
                where = "database directly (--local)" if args.local else "database directly (app not answering)"
            print(f"[tasks] via {be.name}: {where}", file=sys.stderr)
        payload, text = run(args, be)
        if isinstance(be, LocalBackend):
            be.finish()
    except CliError as exc:
        if as_json:
            err: dict[str, Any] = {"error": {"code": exc.code, "message": str(exc)}}
            if exc.detail is not None:
                err["error"]["detail"] = exc.detail
            print(json.dumps(err, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2 if exc.code == "usage" else 1
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via tasks.bat / tests call main()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
