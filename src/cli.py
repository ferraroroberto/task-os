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
    tasks search "q"
    tasks people

Every command takes ``--json`` for machine-readable output (the same shapes
the REST API returns). Talks to the running server over HTTP when it answers
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


class CliError(Exception):
    """A user-facing failure: message + optional structured detail."""

    def __init__(self, message: str, code: str = "error", detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ backends
#
# Both backends expose the same method set and return the same dict shapes,
# so every command formats one way regardless of the transport.

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

    def search(self, q: str) -> list[dict[str, Any]]:
        return self._call("GET", "/api/search?" + urllib.parse.urlencode({"q": q}))["items"]

    def people(self) -> list[dict[str, Any]]:
        return self._call("GET", "/api/people")["items"]


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

    def search(self, q: str) -> list[dict[str, Any]]:
        return self._wrap(self._repo.search, q)

    def people(self) -> list[dict[str, Any]]:
        return self._wrap(self._repo.list_people)


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


def fmt_search(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(no hits)"
    out = []
    for h in items:
        crumb = _crumb(h)
        where = f" in {crumb}" if crumb else ""
        out.append(f"#{h['id']}  {h['title']}{where}\n    {h['matched_in']}: {h['snippet']}")
    return "\n".join(out)


def fmt_people(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(no people)"
    return "\n".join(f"#{p['id']}  {p['name']}" + (f"  <{p['email']}>" if p.get("email") else "")
                     + f"  ({p.get('open_tasks', 0)} open)" for p in items)


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
        items = backend.search(args.query)
        return items, fmt_search(items)
    if cmd == "people":
        items = backend.people()
        return items, fmt_people(items)
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

    se = sub.add_parser("search", parents=[common], help="full-text search")
    se.add_argument("query")

    sub.add_parser("people", parents=[common], help="list people")
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
