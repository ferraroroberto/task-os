"""The ``tasks`` CLI's human-readable text: one formatter per command
output, fed the same dict shapes either backend returns."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.dates import describe_recurrence
from src.schema import CLOSED_STATUSES, DEFAULT_STATUS


def _recurrence_text(t: dict[str, Any]) -> str:
    """A task's cadence + anchor + interval in ``src.dates``' one wording."""
    return describe_recurrence(
        t["recurrence"], t.get("recurrence_anchor"), t.get("recurrence_interval")
    )


def _fmt_task_line(t: dict[str, Any], indent: int = 0) -> str:
    bits = [f"#{t['id']}", t["title"]]
    tail = []
    if t.get("status") and t["status"] != DEFAULT_STATUS:
        tail.append(t["status"])
    if t.get("priority") and t["priority"] != "none":
        tail.append(f"prio {t['priority']}")
    if t.get("due"):
        tail.append(f"due {t['due']}")
    if t.get("starts"):
        tail.append(f"starts {t['starts']}")
    if t.get("recurrence"):
        tail.append(_recurrence_text(t))
    if t.get("type") == "coding" and t.get("issue_ref"):
        tail.append(f"{t['issue_ref']['repo']}#{t['issue_ref']['number']}")
    if t.get("blocked"):
        tail.append(f"blocked by {t['blocker_count']}")
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


def group_journal(items: list[dict[str, Any]], done_from: str, done_to: str) -> dict[str, Any]:
    """The done journal's shape (#102): closed tasks grouped by the local
    calendar day of ``done_at``, newest day first, each day with its count.

    The same grouping the web journal draws — ``done_at`` is a local
    timestamp, so the day is its first ten characters (never UTC
    arithmetic). Both backends hand the list over already ordered newest
    closing first, so the groups come out in order without a sort here.
    """
    days: list[dict[str, Any]] = []
    for t in items:
        day = (t.get("done_at") or "")[:10]
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "count": 0, "items": []})
        days[-1]["items"].append(t)
        days[-1]["count"] += 1
    return {"from": done_from, "to": done_to, "count": len(items), "days": days}


def fmt_journal(journal: dict[str, Any]) -> str:
    if not journal["days"]:
        return f"(nothing closed between {journal['from']} and {journal['to']})"
    lines = []
    for d in journal["days"]:
        when = date.fromisoformat(d["day"]).strftime("%a %d %b") if d["day"] else "(no date)"
        lines.append(f"{when} · {d['count']} done")
        for t in d["items"]:
            mark = "x" if t.get("status") == "done" else "-"
            crumb = _crumb(t)
            lines.append(f"  [{mark}] {_fmt_task_line(t)}" + (f"  {crumb}" if crumb else ""))
    return "\n".join(lines)


def fmt_show(t: dict[str, Any]) -> str:
    lines = [_fmt_task_line(t)]
    crumb = _crumb(t)
    if crumb:
        lines.append(f"  in: {crumb}")
    lines.append(f"  type {t['type']} · status {t['status']} · priority {t['priority']} · due {t.get('due') or '-'}"
                 + (f" · starts {t['starts']}" if t.get("starts") else "")
                 + (f" · {_recurrence_text(t)}" if t.get("recurrence") else ""))
    if t.get("description"):
        lines.append(f"  {t['description']}")
    if t.get("folder_ref"):
        lines.append(f"  folder: {t['folder_ref']}")
    if t.get("next_action"):
        lines.append(f"  next: {t['next_action']}")
    if t.get("blocked_by"):
        lines.append("  blocked by: " + ", ".join(
            f"#{b['id']} {b['title']}" + ("" if b["status"] not in CLOSED_STATUSES else f" ({b['status']})")
            for b in t["blocked_by"]
        ))
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


def fmt_suggestion(item: dict[str, Any]) -> str:
    """One staged Inbox proposal in the same terse shape as the Board strip."""
    fields: list[str] = []
    if item.get("parent"):
        fields.append("→ " + item["parent"]["title"])
    if item.get("priority"):
        fields.append(str(item["priority"]))
    fields.append("due: " + (item.get("due") or "none"))
    if item.get("person"):
        fields.append(str(item["person"]["name"]))
    return (
        f"#{item['task_id']} {item.get('task_title') or ''}\n  "
        + " · ".join(fields)
        + f"\n  {item['reason']}"
    )


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
    lines.append(fmt_capture_status(status.get("capture") or {}))
    lines.append(fmt_voice_status(status.get("voice") or {}))
    lines.append(fmt_enrich_status(status.get("enrich") or {}))
    lines.append(fmt_ai_status(status.get("ai") or {}))
    return "\n".join(lines)


def fmt_capture_status(c: dict[str, Any]) -> str:
    """The flagged-email poller's line (#98) — off always says why."""
    if not c.get("enabled"):
        return f"capture  not configured — {c.get('reason') or 'unknown'}"
    r = c.get("last_result") or {}
    line = (f"capture  enabled · flagged emails every {c.get('poll_minutes')} min"
            f" · last run {c.get('last_run') or '-'}"
            f" · next {c.get('next_run') or '(app not running)'}")
    if c.get("last_run"):
        line += (f" · {r.get('listed', 0)} flagged · {r.get('created', 0)} new"
                 + (f" · {r['dismissed']} dismissed" if r.get("dismissed") else "")
                 + (f" · {len(r.get('errors') or [])} error(s)" if r.get("errors") else ""))
    if c.get("last_error"):
        line += f" · last error {c['last_error']}"
    return line


def fmt_voice_status(v: dict[str, Any]) -> str:
    """The voice endpoints' line (#92, #144) — which one is serving, or why
    neither is."""
    if not v.get("enabled"):
        return f"voice    off — {v.get('reason') or 'unknown'}"
    serving = {"hub": "hub", "fallback": "local whisper (fallback)"}.get(v.get("serving"), "unknown")
    # The live-transcript cadence: a number is "every N s", 0 is the
    # single pass on stop. A missing key is neither, and says so.
    interval = v.get("partial_interval_seconds")
    if interval is None:
        live = "live transcript unknown"
    elif interval > 0:
        live = f"live every {interval:g}s"
    else:
        live = "live transcript off"
    return (f"voice    reachable · {serving} · {live} · {v.get('url')}"
            + (f" · checked {v['checked_at']}" if v.get("checked_at") else ""))


def fmt_enrich_status(e: dict[str, Any]) -> str:
    """The text model's line (#147) — which model, or why there is none.

    Off is never silent: a spoken line still becomes a task, it just keeps
    the deterministic parse, and this is where you find out that is what you
    have been getting."""
    if not e.get("enabled"):
        return f"enrich   off — {e.get('reason') or 'unknown'}"
    return (f"enrich   reachable · {e.get('model')} · {e.get('url')}"
            + (f" · checked {e['checked_at']}" if e.get("checked_at") else ""))


def fmt_ai_status(ai: dict[str, Any]) -> str:
    """The shared local AI client's state — disabled and down stay distinct."""
    if not ai.get("enabled"):
        return f"ai       off — {ai.get('reason') or 'unknown'}"
    return (f"ai       reachable · {ai.get('model') or 'model unknown'}"
            + (f" · checked {ai['checked_at']}" if ai.get("checked_at") else ""))


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
