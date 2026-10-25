"""The mirror's file format: one task as a markdown file with YAML-ish
frontmatter, and the parser that reads one back. Pure text in, text out — no
database, no folder; ``src/mirror.py`` does the export and the watcher import."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

SLUG_MAX = 60

FILE_RE = re.compile(r"^(\d{4,})(?:-[^\\/]*)?\.md$", re.IGNORECASE)
_HEADINGS = {"## description": "description", "## comments": "comments", "## log": "log"}
_COMMENT_RE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
    r" · (?P<author>.*?) · (?P<origin>[a-z]+): (?P<body>.*)$"
)
_INT_RE = re.compile(r"^-?\d+$")
_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./ ,+():@%\u00c0-\uffff-]*$")

#: Frontmatter keys, in the order they are written.
FRONTMATTER_KEYS = (
    "id", "external_id", "parent", "title", "code", "type", "status", "priority", "due",
    "starts", "recurrence", "recurrence_anchor", "recurrence_interval", "person",
    "folder_ref", "next_action", "blocked_by", "links",
    "created_at", "updated_at", "done_at", "exported_at",
)


class MirrorParseError(ValueError):
    """The file is not a mirror file we can read (bad frontmatter, no id, …)."""



# ================================================================ rendering


def slugify(title: str) -> str:
    """``"Renew passports (2026)"`` → ``renew-passports-2026``; ASCII, ≤ 60 chars, never empty."""
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    text = text[:SLUG_MAX].rstrip("-")
    return text or "task"


def file_name(task_id: int, title: str) -> str:
    return f"{int(task_id):04d}-{slugify(title)}.md"


def _needs_quotes(s: str) -> bool:
    if s == "" or s != s.strip():
        return True
    low = s.lower()
    if low in ("null", "~", "true", "false", "yes", "no", "on", "off") or _INT_RE.match(s):
        return True
    if s[0] in "-?:,[]{}#&*!|>'\"%@`" or ": " in s or " #" in s or "\n" in s:
        return True
    return not _PLAIN_SAFE_RE.match(s)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    return json.dumps(s, ensure_ascii=False) if _needs_quotes(s) else s


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s in ("", "null", "~", "Null", "NULL"):
        return None
    if s.startswith('"'):
        try:
            return json.loads(s)
        except ValueError as exc:
            raise MirrorParseError(f"bad quoted string {s[:40]!r}") from exc
    if s.startswith("'"):
        if not s.endswith("'") or len(s) < 2:
            raise MirrorParseError(f"unterminated string {s[:40]!r}")
        return s[1:-1].replace("''", "'")
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if _INT_RE.match(s):
        return int(s)
    return s


def render(task: dict[str, Any], *, exported_at: str) -> str:
    """The canonical file text for a ``tasks_repo.get_task`` detail dict."""
    fm: dict[str, Any] = {
        "id": task["id"],
        "external_id": task.get("external_id"),
        "parent": task.get("parent_id"),
        "title": task["title"],
        "code": task.get("code"),
        "type": task.get("type"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "due": task.get("due"),
        "starts": task.get("starts"),
        "recurrence": task.get("recurrence"),
        "recurrence_anchor": task.get("recurrence_anchor"),
        "recurrence_interval": task.get("recurrence_interval"),
        "person": (task.get("person") or {}).get("name"),
        "folder_ref": task.get("folder_ref"),
        "next_action": task.get("next_action"),
        "blocked_by": [b["id"] for b in task.get("blocked_by") or []],
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "done_at": task.get("done_at"),
        "exported_at": exported_at,
    }
    lines = ["---"]
    for key in FRONTMATTER_KEYS:
        if key == "blocked_by":
            ids = fm["blocked_by"]
            lines.append("blocked_by: [" + ", ".join(str(i) for i in ids) + "]")
            continue
        if key == "links":
            links = task.get("links") or []
            if not links:
                lines.append("links: []")
            else:
                lines.append("links:")
                for lk in links:
                    lines.append(f"  - url: {_scalar(lk.get('url'))}")
                    lines.append(f"    label: {_scalar(lk.get('label'))}")
                    lines.append(f"    kind: {_scalar(lk.get('kind') or 'web')}")
            continue
        lines.append(f"{key}: {_scalar(fm[key])}")
    lines.append("---")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    desc = (task.get("description") or "").strip()
    if desc:
        lines.append(desc)
        lines.append("")
    lines.append("## Comments")
    lines.append("")
    for c in task.get("comments") or []:
        lines.append(_comment_line(c))
    if task.get("comments"):
        lines.append("")
    lines.append("## Log")
    lines.append("")
    activity = list(task.get("activity") or [])
    activity.reverse()  # get_task gives newest first; a log reads oldest first
    for a in activity:
        old = "∅" if a.get("old_value") is None else str(a["old_value"]).replace("\n", " ")
        new = "∅" if a.get("new_value") is None else str(a["new_value"]).replace("\n", " ")
        lines.append(f"- {a['ts']} · {a.get('actor') or '-'} · {a['field']}: {old} → {new}")
    if activity:
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _comment_line(c: dict[str, Any]) -> str:
    body = (c.get("body") or "").strip()
    first, *rest = body.split("\n")
    out = f"- {c['ts']} · {c.get('author') or '-'} · {c.get('origin') or 'ui'}: {first}"
    for extra in rest:
        out += "\n  " + extra
    return out


# ================================================================== parsing


@dataclass
class ParsedFile:
    frontmatter: dict[str, Any]
    description: str
    comments: list[dict[str, Any]]  # {ts, author, origin, body} (ts/author/origin None on a bare line)
    sections: dict[str, str] = field(default_factory=dict)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(mapping, body)`` for a ``---`` fenced YAML head; the tiny YAML subset we write."""
    if not text.startswith("---"):
        raise MirrorParseError("missing frontmatter fence")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise MirrorParseError("missing frontmatter fence")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        raise MirrorParseError("unterminated frontmatter")
    data: dict[str, Any] = {}
    i = 1
    while i < end:
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise MirrorParseError(f"unexpected indentation at frontmatter line {i}: {line[:40]!r}")
        if ":" not in line:
            raise MirrorParseError(f"expected 'key: value' at frontmatter line {i}: {line[:40]!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        if not key or " " in key:
            raise MirrorParseError(f"bad key at frontmatter line {i}: {line[:40]!r}")
        rest_s = rest.strip()
        if rest_s == "":
            # block: a list of mappings ("  - k: v" / "    k: v") or nothing
            items: list[dict[str, Any]] = []
            while i < end and (lines[i].startswith(" ") or not lines[i].strip()):
                sub = lines[i]
                i += 1
                st = sub.strip()
                if not st:
                    continue
                if st.startswith("- "):
                    items.append({})
                    st = st[2:].strip()
                    if not st:
                        continue
                elif not items:
                    raise MirrorParseError(f"unexpected nested line at frontmatter line {i}: {sub[:40]!r}")
                if ":" not in st:
                    raise MirrorParseError(f"expected 'key: value' in list at frontmatter line {i}: {sub[:40]!r}")
                k, _, v = st.partition(":")
                items[-1][k.strip()] = _parse_scalar(v)
            data[key] = items
        elif rest_s in ("[]", "[ ]"):
            data[key] = []
        elif rest_s.startswith("[") and rest_s.endswith("]"):
            # An inline scalar list — only ``blocked_by: [3, 7]`` writes this
            # shape today, so an int-only reader is enough; anything else is
            # malformed rather than silently coerced.
            inner = rest_s[1:-1].strip()
            items_flat: list[Any] = []
            for part in inner.split(","):
                part = part.strip()
                if not part:
                    continue
                if not _INT_RE.match(part):
                    raise MirrorParseError(f"expected an integer list at frontmatter line {i}: {line[:40]!r}")
                items_flat.append(int(part))
            data[key] = items_flat
        else:
            data[key] = _parse_scalar(rest_s)
    body = "\n".join(lines[end + 1:])
    return data, body


def split_sections(body: str) -> dict[str, str]:
    """``{"description": …, "comments": …, "log": …}`` by the three known ``##`` headings."""
    out: dict[str, list[str]] = {}
    current = "_preamble"
    for line in body.split("\n"):
        key = _HEADINGS.get(line.strip().lower())
        if key is not None:
            current = key
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def parse_comment_lines(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in text.split("\n"):
        if line.startswith("- "):
            m = _COMMENT_RE.match(line)
            if m:
                entries.append({
                    "ts": m.group("ts"), "author": m.group("author"),
                    "origin": m.group("origin"), "body": m.group("body"),
                })
            else:
                entries.append({"ts": None, "author": None, "origin": None, "body": line[2:]})
        elif entries and line.strip():
            entries[-1]["body"] += "\n" + (line[2:] if line.startswith("  ") else line.strip())
        elif entries and not line.strip():
            entries[-1]["body"] += "\n"
    for e in entries:
        e["body"] = e["body"].strip()
    return [e for e in entries if e["body"]]


def parse_file(text: str) -> ParsedFile:
    fm, body = parse_frontmatter(text.lstrip("\ufeff"))
    if not isinstance(fm.get("id"), int):
        raise MirrorParseError("frontmatter has no integer id")
    sections = split_sections(body)
    return ParsedFile(
        frontmatter=fm,
        description=sections.get("description", "").strip(),
        comments=parse_comment_lines(sections.get("comments", "")),
        sections=sections,
    )
