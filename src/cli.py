"""``tasks`` — the terminal / scripting / LLM surface of task-os.

    tasks add "Renew passport" --due fri [--starts oct 1] [--parent N] [--priority high]
              [--recurrence weekly [--recurrence-anchor fri] [--recurrence-interval 7]]
              [--person "Sam"] [--owner <member id>]
              [--desc "..."] [--folder "{onedrive}/..."] [--link URL [--link-label "..."]]
    tasks ls [--status todo,standby|open|all] [--project N] [--due today|week|overdue]
             [--deferred] [--blocked] [--updated-before <date|30d>] [--owner <member id>[,…]]
    tasks show N
    tasks tree [N]
    tasks comment N "text"
    tasks set N [--title] [--status] [--priority] [--desc] [--folder ref|none] [--owner id]   edit fields (#257)
    tasks link N URL [--label "..."] [--kind web|folder|email|issue|ai]   kind inferred when omitted
    tasks due N <date>          natural (fri, next friday, in 2 weeks) or ISO; "none" clears
    tasks starts N <date>       the day it starts mattering; same vocabulary, "none" clears
    tasks done N
    tasks journal [--weeks N]   what got done, grouped by day, newest first (#102)
    tasks move N --parent M     (--parent root → top level)
    tasks block N --on M        N is blocked by M — refused on a self-block or a cycle (#100)
    tasks unblock N M           remove M as a blocker of N
    tasks rm N [--yes]          delete N and its subtree — asks [y/N] on stderr; alias: delete (#121)
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
server over HTTP(S) when it answers
(``https://127.0.0.1:<config port>`` when the cert pair exists, else
``http://…``; override with ``--server URL`` /
``TASKOS_URL``); otherwise — app down — it opens the database directly, so
the CLI works either way. ``--local`` forces the direct path. ``--actor``
names who is acting (activity / comment author); default = the configured
first team member.

A task whose ``--starts`` day has not arrived is *deferred*: ``tasks ls``
leaves it out (as do the web app's Board and Today), ``tasks ls
--deferred`` is the list of exactly those, ``tasks ls --status all`` shows
everything including them, and ``tasks show`` / ``tasks tree`` / ``tasks
search`` always find it.

Exit codes: 0 ok · 1 error (message on stderr, or the JSON error envelope
with ``--json``) · 2 usage.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from src import clock
from src.cli_support.backends import UNKNOWN, CliError, HttpBackend, LocalBackend, _tls_context
from src.cli_support.format import (
    _crumb,
    _fmt_task_line,
    _recurrence_text,
    fmt_folders_search,
    fmt_folders_status,
    fmt_issues_status,
    fmt_journal,
    fmt_ls,
    fmt_people,
    fmt_search,
    fmt_show,
    fmt_status,
    fmt_suggestion,
    fmt_tree,
    group_journal,
)
from src.config import load_config
from src.dates import DateParseError, days_ago, parse_date, parse_days_ago
from src.schema import (
    DEFAULT_STATUS,
    LINK_KINDS,
    RECURRENCES,
    TASK_PRIORITIES,
    TASK_STATUSES,
)

logger = logging.getLogger(__name__)

SERVER_ENV = "TASKOS_URL"
PROBE_TIMEOUT_S = 0.8

__all__ = ["UNKNOWN", "CliError", "HttpBackend", "LocalBackend"]


def server_answers(base: str, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """One short ``/healthz`` probe — is the app up?"""
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=timeout, context=_tls_context(base)) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError):
        return False


def pick_backend(args: argparse.Namespace) -> HttpBackend | LocalBackend:
    config = load_config()
    actor = args.actor or (config.team.people[0] if config.team.people else None)
    if args.local:
        return LocalBackend(actor)
    explicit = args.server or os.environ.get(SERVER_ENV, "").strip()
    if explicit:
        if server_answers(explicit):
            return HttpBackend(explicit, actor)
        raise CliError(f"nothing answers {explicit}/healthz (drop --server / {SERVER_ENV} to use the database directly)")
    for base in _default_bases(config.port):
        if server_answers(base):
            return HttpBackend(base, actor)
    return LocalBackend(actor)


def _default_bases(port: int) -> list[str]:
    """Where the app is on this PC: HTTPS first when the cert pair exists (the
    tray then serves TLS — ``src/certs.py``), plain HTTP always as the second
    try, like the tray's own probe (#259)."""
    from src import certs

    plain = f"http://127.0.0.1:{port}"
    return [f"https://127.0.0.1:{port}", plain] if certs.cert_paths() else [plain]


# ------------------------------------------------------------------ commands


def _parse_date_arg(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        d = parse_date(text)
    except DateParseError as exc:
        raise CliError(str(exc), code="bad_date") from exc
    return d.isoformat() if d else None


def _parse_before_arg(text: str) -> str:
    """``--updated-before`` vocabulary: ``Nd`` = N days ago, else a date.

    The relative form is :func:`src.dates.parse_days_ago`'s, resolved CLI-side —
    the wire (and the repo layer) only ever see a plain date, same as the web
    filter card (#101).
    """
    ago = parse_days_ago(text)
    if ago is not None:
        return ago.isoformat()
    parsed = _parse_date_arg(text)
    if parsed is None:
        raise CliError(f"cannot parse date {text!r}", code="bad_date")
    return parsed


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


def _rm_dialogue(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    """``tasks rm`` / ``delete`` — the [y/N] confirmation (skipped by ``--yes``), then the delete."""
    # Delete with a confirmation that names what goes. The
    # dialogue is on stderr — stdout stays clean for --json — and a
    # refusal is an error, so a script that forgot --yes fails loud
    # instead of half-working.
    t = backend.show(args.id)
    n = int(t.get("descendant_count") or 0)
    ref = t.get("issue_ref") or {}
    if not args.yes:
        say = lambda text: print(text, file=sys.stderr)  # noqa: E731
        say(_fmt_task_line(t))
        if n:
            say(f"  and its {n} child task{'s' if n != 1 else ''}")
        if ref.get("state") == "open":
            say(f"  synced coding task: the next issue sync recreates it while "
                f"{ref.get('repo')}#{ref.get('number')} stays open — unlink it first, or close the issue")
        say("  delete? This cannot be undone. [y/N] ")
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            raise CliError(f"#{args.id} not deleted", code="cancelled")
    r = backend.delete(args.id)
    gone = int(r.get("deleted") or 1)
    tail = f" ({gone} tasks)" if gone > 1 else ""
    return r, f"#{r['id']} deleted{tail}"


def _triage_dialogue(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    """``tasks triage`` — y/n/q over each staged AI suggestion; ``--json`` never asks."""
    items = backend.triage()
    # JSON is the automation surface: stage and expose the exact rows,
    # never stop a pipe to ask a question.
    if getattr(args, "json", False):
        return {"items": items}, ""
    accepted: list[int] = []
    rejected: list[int] = []
    pending: list[int] = []
    print(
        f"{len(items)} staged suggestion(s) — [y] accept · [n] reject · "
        "[q] leave the rest pending",
        file=sys.stderr,
    )
    for index, item in enumerate(items):
        print(fmt_suggestion(item), file=sys.stderr)
        print("  accept and move to Todo? [y/n/q] ", file=sys.stderr)
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = "q"
        if answer == "q":
            pending.extend(int(rest["id"]) for rest in items[index:])
            break
        if answer in ("y", "yes"):
            backend.accept_suggestion(int(item["id"]))
            accepted.append(int(item["id"]))
        else:
            backend.reject_suggestion(int(item["id"]))
            rejected.append(int(item["id"]))
    result = {
        "items": items,
        "accepted": accepted,
        "rejected": rejected,
        "pending": pending,
    }
    return result, (
        f"triage: {len(accepted)} accepted · {len(rejected)} rejected · "
        f"{len(pending)} pending"
    )


def _folder_arg(value: str) -> str | None:
    """``--folder`` → the stored ref: ``none`` / empty clears, an absolute path
    folds onto the configured placeholders (``{onedrive}/…``) exactly as the
    drawer's ``POST /api/resolve`` does, so the chip opens on any PC (#257)."""
    from src import placeholders

    if value.strip().lower() in ("", "none"):
        return None
    return placeholders.to_ref(value, load_config().placeholders) or None


def _cmd_add(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    fields: dict[str, Any] = {"title": args.title}
    if args.parent is not None:
        fields["parent_id"] = _parent_arg(args.parent)
    if args.due is not None:
        fields["due"] = _parse_date_arg(args.due)
    if args.starts is not None:
        fields["starts"] = _parse_date_arg(args.starts)
    if args.status:
        fields["status"] = args.status
    if args.priority:
        fields["priority"] = args.priority
    if args.recurrence:
        fields["recurrence"] = args.recurrence
    if args.recurrence_anchor:
        fields["recurrence_anchor"] = args.recurrence_anchor
    if args.recurrence_interval is not None:
        fields["recurrence_interval"] = args.recurrence_interval
    if args.person:
        fields["person_id"] = _resolve_person(backend, args.person)
    if args.owner:
        fields["owner"] = args.owner
    if args.desc:
        fields["description"] = args.desc
    if args.folder:
        fields["folder_ref"] = _folder_arg(args.folder)
    if args.link_label and not args.link:
        raise CliError("--link-label needs --link", code="usage")
    t = backend.add(**fields)
    if args.link:
        # a second call: the task already exists if this one fails, so
        # the error names it rather than implying nothing was written
        try:
            backend.link(t["id"], args.link, args.link_label, None)
        except CliError as exc:
            raise CliError(f"added #{t['id']}, but the link failed: {exc}", code=exc.code,
                           detail=exc.detail) from exc
        t = backend.show(t["id"])
    return t, f"added {_fmt_task_line(t)}"


def _cmd_ls(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
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
    if args.owner:
        filters["owner"] = args.owner
    if args.deferred:
        filters["deferred"] = True
    if args.blocked:
        filters["blocked"] = True
    if args.updated_before:
        filters["updated_before"] = _parse_before_arg(args.updated_before)
    items = backend.ls(**filters)
    return items, fmt_ls(items)


def _cmd_journal(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    weeks = args.weeks if args.weeks and args.weeks > 0 else 1
    done_to = clock.today().isoformat()
    done_from = days_ago(7 * weeks - 1).isoformat()
    filters = {"status": "done,cancelled", "done_from": done_from, "done_to": done_to}
    if args.project is not None:
        filters["project"] = args.project
    if args.person:
        filters["person"] = _resolve_person(backend, args.person)
    journal = group_journal(backend.ls(**filters), done_from, done_to)
    return journal, fmt_journal(journal)


def _cmd_show(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.show(args.id)
    return t, fmt_show(t)


def _cmd_tree(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    nodes = backend.tree(args.id)
    return nodes, "\n".join(fmt_tree(nodes)) or "(no tasks)"


def _cmd_comment(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    c = backend.comment(args.id, args.text)
    return c, f"commented on #{args.id}: {c['body']}"


def _cmd_set(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    changes: dict[str, Any] = {}
    if args.title is not None:
        changes["title"] = args.title
    if args.status:
        changes["status"] = args.status
    if args.priority:
        changes["priority"] = args.priority
    if args.desc is not None:
        changes["description"] = args.desc
    if args.folder is not None:
        changes["folder_ref"] = _folder_arg(args.folder)
    if args.owner:
        changes["owner"] = args.owner
    if not changes:
        raise CliError("set needs at least one of --title --status --priority --desc --folder --owner", code="usage")
    t = backend.update(args.id, **changes)
    return t, f"updated {_fmt_task_line(t)}"


def _cmd_link(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    lk = backend.link(args.id, args.url, args.label, args.kind)
    return lk, f"#{args.id} linked [{lk['kind']}] {lk.get('label') or lk['url']}"


def _cmd_due(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.due(args.id, _parse_date_arg(args.date))
    return t, f"#{t['id']} due → {t.get('due') or 'none'}"


def _cmd_starts(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.starts(args.id, _parse_date_arg(args.date))
    return t, f"#{t['id']} starts → {t.get('starts') or 'none'}"


def _cmd_done(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.done(args.id)
    if t.get("recurrence"):
        label = _recurrence_text(t)
        return t, f"#{t['id']} done — recurring {label}, next due {t['due']}"
    return t, f"#{t['id']} done"


def _cmd_move(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.move(args.id, _parent_arg(args.parent))
    where = _crumb(t) or "top level"
    return t, f"#{t['id']} moved → {where}"


def _cmd_block(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.block(args.id, args.on)
    return t, f"#{t['id']} blocked by #{args.on} ({t['blocker_count']} open blocker(s))"


def _cmd_unblock(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.unblock(args.id, args.blocker)
    return t, f"#{t['id']} unblocked from #{args.blocker} ({t['blocker_count']} open blocker(s) left)"


def _cmd_search(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    kinds = [args.kind] if getattr(args, "kind", None) else None
    result = backend.search(args.query, kinds)
    return result, fmt_search(result)


def _cmd_people(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    items = backend.people()
    return items, fmt_people(items)


def _cmd_mirror(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
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


def _cmd_backup(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    r = backend.backup()
    return r, f"backup written: {r['path']}"


def _cmd_issues(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
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


def _cmd_issue(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    t = backend.issue_create(args.id, args.repo)
    ref = t.get("issue_ref") or {}
    return t, f"#{t['id']} → {ref.get('repo')}#{ref.get('number')} {ref.get('url') or ''}".rstrip()


def _cmd_folders(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
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


#: One handler per subcommand → (json payload, human text).
_COMMANDS: dict[str, Callable[[argparse.Namespace, HttpBackend | LocalBackend], tuple[Any, str]]] = {
    "add": _cmd_add,
    "ls": _cmd_ls,
    "journal": _cmd_journal,
    "show": _cmd_show,
    "tree": _cmd_tree,
    "comment": _cmd_comment,
    "set": _cmd_set,
    "link": _cmd_link,
    "due": _cmd_due,
    "starts": _cmd_starts,
    "done": _cmd_done,
    "rm": _rm_dialogue,
    "move": _cmd_move,
    "block": _cmd_block,
    "unblock": _cmd_unblock,
    "search": _cmd_search,
    "people": _cmd_people,
    "triage": _triage_dialogue,
    "mirror": _cmd_mirror,
    "backup": _cmd_backup,
    "issues": _cmd_issues,
    "issue": _cmd_issue,
    "folders": _cmd_folders,
}


def run(args: argparse.Namespace, backend: HttpBackend | LocalBackend) -> tuple[Any, str]:
    """Execute one command → (json payload, human text)."""
    cmd = "rm" if args.command == "delete" else args.command   # `delete` is rm's alias
    handler = _COMMANDS.get(cmd)
    if handler is None:
        raise CliError(f"unknown command {cmd!r}", code="usage")
    return handler(args, backend)


# ---------------------------------------------------------------- argparse


def _add_task_commands(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """Create and read: add · ls · journal · show · tree · comment · set."""
    a = sub.add_parser("add", parents=[common], help="add a task")
    a.add_argument("title")
    a.add_argument("--parent", help="parent task id (nesting)")
    a.add_argument("--due", help="today · tomorrow · fri · next friday · in 2 weeks · YYYY-MM-DD")
    a.add_argument("--starts", help="the day it starts mattering — hidden from the working views until then")
    a.add_argument(
        "--status", choices=TASK_STATUSES,
        help=f"where it starts (default {DEFAULT_STATUS}) — `inbox` for something to triage later",
    )
    a.add_argument("--priority", choices=TASK_PRIORITIES)
    a.add_argument("--recurrence", choices=RECURRENCES)
    a.add_argument(
        "--recurrence-anchor",
        help="the fixed day it lands on — weekly: fri or mon,tue,wed,thu,fri · "
             "monthly: day-15, 1-sun, last-fri",
    )
    a.add_argument(
        "--recurrence-interval", type=int, metavar="N",
        help="repeat every N cadences — --recurrence weekly --recurrence-anchor sat "
             "--recurrence-interval 7 is every 7 weeks on Saturday",
    )
    a.add_argument("--person", help="person id or name")
    a.add_argument("--owner", help="the member whose task it is (a people id; default: you)")
    a.add_argument("--desc", help="description (markdown)")
    a.add_argument("--folder", help="folder ref ({onedrive}/…) or absolute path — the per-PC opener's chip")
    a.add_argument("--link", help="one link to attach (its kind is inferred: an AI chat URL wears the bot chip)")
    a.add_argument("--link-label", help="label for --link")

    ls = sub.add_parser("ls", parents=[common], help="list tasks")
    ls.add_argument("--status", help=f"comma list of {','.join(TASK_STATUSES)} · open (default) · all")
    ls.add_argument("--project", type=int, help="only descendants of this task")
    ls.add_argument("--due", help="today · week · overdue · YYYY-MM-DD")
    ls.add_argument("--person", help="person id or name")
    ls.add_argument("--owner", help="comma list of member ids — the install owner's include tasks nobody gave one")
    ls.add_argument("--updated-before",
                    help="only tasks last touched strictly before this day (a date, or Nd = N days ago)")
    ls.add_argument("--deferred", action="store_true",
                    help="only tasks still sleeping (a start date in the future)")
    ls.add_argument("--blocked", action="store_true",
                    help="only tasks with an open blocker (#100)")

    j = sub.add_parser("journal", parents=[common],
                       help="what got done, grouped by day, newest first (this week by default)")
    j.add_argument("--weeks", type=int, default=1, help="how many weeks back (7-day steps ending today)")
    j.add_argument("--project", type=int, help="only descendants of this task")
    j.add_argument("--person", help="person id or name")

    s = sub.add_parser("show", parents=[common], help="task detail with comments + activity")
    s.add_argument("id", type=int)

    t = sub.add_parser("tree", parents=[common], help="nested view")
    t.add_argument("id", type=int, nargs="?", help="root task (default: everything)")

    c = sub.add_parser("comment", parents=[common], help="add a comment")
    c.add_argument("id", type=int)
    c.add_argument("text")

    se_ = sub.add_parser("set", parents=[common], help="edit fields — title, status, priority, description, folder, owner")
    se_.add_argument("id", type=int)
    se_.add_argument("--title")
    se_.add_argument("--status", choices=TASK_STATUSES,
                     help="done here does not roll a recurring task — use `tasks done` for that")
    se_.add_argument("--priority", choices=TASK_PRIORITIES)
    se_.add_argument("--desc", help="replace the description (markdown); \"\" clears")
    se_.add_argument("--folder", help="folder ref or absolute path; 'none' clears")
    se_.add_argument("--owner", help="hand the task to another member (a people id)")


def _add_edit_commands(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """One-field edits on a task: link · due · starts · done · move · block · unblock · rm."""
    lk = sub.add_parser("link", parents=[common], help="attach a link to a task")
    lk.add_argument("id", type=int)
    lk.add_argument("url")
    lk.add_argument("--label")
    lk.add_argument("--kind", choices=LINK_KINDS, help="default: inferred from the URL")

    d = sub.add_parser("due", parents=[common], help="set the due date")
    d.add_argument("id", type=int)
    d.add_argument("date", help="natural or ISO; 'none' clears")

    st = sub.add_parser("starts", parents=[common],
                        help="set the start date (snooze — hidden until then)")
    st.add_argument("id", type=int)
    st.add_argument("date", help="natural or ISO; 'none' clears")

    dn = sub.add_parser("done", parents=[common], help="complete (recurring tasks roll forward)")
    dn.add_argument("id", type=int)

    m = sub.add_parser("move", parents=[common], help="re-parent")
    m.add_argument("id", type=int)
    m.add_argument("--parent", required=True, help="new parent id, or 'root'")

    bl = sub.add_parser("block", parents=[common], help="add a blocker (#100) — N is blocked by M")
    bl.add_argument("id", type=int)
    bl.add_argument("--on", type=int, required=True, help="the blocker's task id")

    ub = sub.add_parser("unblock", parents=[common], help="remove a blocker (#100)")
    ub.add_argument("id", type=int)
    ub.add_argument("blocker", type=int, help="the blocker task id to remove")

    rm = sub.add_parser("rm", parents=[common], aliases=["delete"],
                        help="delete a task and its subtree (asks first; --yes for scripts)")
    rm.add_argument("id", type=int)
    rm.add_argument("--yes", "-y", action="store_true", help="skip the confirmation")


def _add_service_commands(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    """The install's services: search · people · triage · mirror · backup · issues · issue · folders."""
    se = sub.add_parser("search", parents=[common], help="federated search: tasks · folders · emails · issues")
    se.add_argument("query")
    se.add_argument("--kind", choices=("tasks", "folders", "emails", "issues"), default=None,
                    help="one index only (default: all four)")

    sub.add_parser("people", parents=[common], help="list people")

    sub.add_parser(
        "triage", parents=[common],
        help="stage AI suggestions for Inbox tasks and accept/reject them one by one",
    )

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

    _add_task_commands(sub, common)
    _add_edit_commands(sub, common)
    _add_service_commands(sub, common)
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
