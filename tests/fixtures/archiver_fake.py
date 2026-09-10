"""A fake email-archiver checkout — the subprocess boundary, without Outlook.

``src/archive_batch.py`` never imports the archiver: it spawns
``<archive.python> main_batch.py <verb>`` and reads one JSON document back. So
the honest fake is not a monkeypatched ``subprocess.run`` but a **real
checkout**: :func:`build_fake_archiver` writes a ``main_batch.py`` and a
``main_scan.py`` into a temp folder, and the tests point ``archive.python`` at
``sys.executable``. Everything the service actually has to get right then runs
for real — the argv it builds, the temp decisions file it writes, the UTF-8
decode of the child's stdout, the exit codes, the timeout.

The fake reads its answers from ``_responses.json`` beside it and records every
invocation into ``_calls.jsonl`` (``{verb, argv, payload}``), which is what lets
a test assert the one thing the archiver's author asked for: that a candidate's
``date_prefix`` is handed back **unchanged** on the ``apply`` decision.

Synthetic throughout, as everything on screen and in a fixture here must be
(public repo): the subjects, senders and folders below are invented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: A folder the fake ranks first, with the archiver's own per-folder naming
#: inference already applied — the value that must come back untouched.
FOLDER_HOUSE = "E:\\archive\\house\\heating"
FOLDER_BILLS = "E:\\archive\\admin\\bills"


def candidate(folder: str, score: float, *, date_prefix: bool = False, name: str = "") -> dict[str, Any]:
    return {
        "folder_path": folder,
        "display_name": name or folder.rsplit("\\", 1)[-1],
        "score": score,
        "match_count": 3,
        "sample_subjects": ["a previous thread"],
        "date_prefix": date_prefix,
    }


def mail(
    message_id: str,
    *,
    subject: str = "A synthetic subject",
    sender: str = "someone@example.invalid",
    candidates: list[dict[str, Any]] | None = None,
    already_archived: str | None = None,
    attachments: int = 0,
    in_inbox: bool | None = True,
) -> dict[str, Any]:
    """One ``plan`` mail.

    ``in_inbox`` is what today's archiver states on every mail it reports
    (email-archiver#59): always ``True``, because ``plan`` enumerates the Inbox,
    and the fact that separates an ``already_archived`` mail *still sitting in
    the Inbox* from one that is properly filed and gone. ``None`` omits the key
    altogether — the document an **older** archiver produces, which is the case
    a defensive reader has to keep the old no-op for.
    """
    doc = {
        "message_id": message_id,
        "entry_id": f"ENTRY-{message_id}",
        "subject": subject,
        "sender": sender,
        "recipients": ["me@example.invalid"],
        "date_sent": "2026-09-01T09:15:00+02:00",
        "body_preview": "Synthetic preview text.",
        "attachment_count": attachments,
        "flag_status": 0,
        "already_archived": already_archived,
        "candidates": list(candidates or []),
    }
    if in_inbox is not None:
        doc["in_inbox"] = in_inbox
    return doc


def plan_doc(mails: list[dict[str, Any]], *, skipped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    already = sum(1 for m in mails if m.get("already_archived"))
    return {
        "verb": "plan",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:00:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {
            "inbox": len(mails) + len(skipped or []),
            "planned": len(mails) - already,
            "already_archived": already,
            "skipped": len(skipped or []),
        },
        "mails": mails,
        "skipped": list(skipped or []),
    }


def apply_result(
    message_id: str,
    folder: str,
    *,
    ok: bool = True,
    files: list[str] | None = None,
    error: dict[str, str] | None = None,
    sequence: str = "0042",
    reused: bool = False,
    move_via: str = "original",
) -> dict[str, Any]:
    """One ``apply`` result.

    ``reused`` and ``move_via`` arrived with email-archiver#59 and are what a
    *finish* looks like from the outside: ``reused: true`` with the existing
    file listed and an **empty** ``sequence_number`` (none was allocated),
    because nothing was written. ``move_via`` names which of the three move
    paths finished it — ``refetched`` · ``saved_retry`` · ``original``.
    """
    return {
        "message_id": message_id,
        "folder_path": folder,
        "ok": ok,
        "sequence_number": sequence,
        "files": list(files or []),
        "entry_id": f"MOVED-{message_id}" if ok else "",
        "moved": ok,
        "categorized": ok,
        "reused": reused,
        "move_via": move_via if ok else None,
        "error": error,
    }


def apply_doc(results: list[dict[str, Any]]) -> dict[str, Any]:
    applied = sum(1 for r in results if r["ok"])
    return {
        "verb": "apply",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:01:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {"requested": len(results), "applied": applied, "failed": len(results) - applied},
        "results": results,
    }


def revert_result(
    message_id: str, *, ok: bool = True, deleted: list[str] | None = None,
    error: dict[str, str] | None = None, refused: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "ok": ok,
        "deleted": list(deleted or []),
        "missing": [],
        "refused": list(refused or []),
        "file_errors": [],
        "moved_back": ok,
        "category_removed": ok,
        "entry_id": f"BACK-{message_id}" if ok else "",
        "error": error,
    }


def revert_doc(results: list[dict[str, Any]]) -> dict[str, Any]:
    reverted = sum(1 for r in results if r["ok"])
    return {
        "verb": "revert",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:02:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {"requested": len(results), "reverted": reverted, "failed": len(results) - reverted},
        "results": results,
    }


def error_doc(verb: str, code: str, message: str) -> dict[str, Any]:
    return {
        "verb": verb,
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:00:00+02:00",
        "error": {"code": code, "message": message},
    }


_MAIN_BATCH = '''\
"""A stand-in for email-archiver's main_batch.py — canned answers, no Outlook."""
import argparse, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-timeout", type=float, default=60.0)
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("plan"); p.add_argument("--candidates", type=int, default=10)
    a = sub.add_parser("apply"); a.add_argument("--decisions", required=True)
    r = sub.add_parser("revert"); r.add_argument("--items", required=True)
    args = parser.parse_args()

    responses = _load("_responses.json")
    payload = None
    source = getattr(args, "decisions", None) or getattr(args, "items", None)
    if source:
        with open(source, encoding="utf-8") as fh:
            payload = json.load(fh)
    with open(os.path.join(HERE, "_calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"verb": args.verb, "argv": sys.argv[1:], "payload": payload}) + "\\n")

    time.sleep(float(responses.get("sleep", 0)))
    answers = responses.get(args.verb) or []
    index = min(responses.setdefault("_seen_" + args.verb, 0), len(answers) - 1)
    responses["_seen_" + args.verb] = index + 1
    with open(os.path.join(HERE, "_responses.json"), "w", encoding="utf-8") as fh:
        json.dump(responses, fh)

    document = answers[index] if answers else {}
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(document, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\\n")
    return int(responses.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
'''

_MAIN_SCAN = '''\
"""A stand-in for email-archiver's main_scan.py — prints, never indexes."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "_responses.json"), encoding="utf-8") as fh:
    responses = json.load(fh)
print("scanned (fake)")
sys.exit(int(responses.get("scan_exit_code", 0)))
'''


def build_fake_archiver(
    root: Path,
    *,
    plan: list[dict[str, Any]] | None = None,
    apply: list[dict[str, Any]] | None = None,
    revert: list[dict[str, Any]] | None = None,
    exit_code: int = 0,
    scan_exit_code: int = 0,
    sleep: float = 0.0,
    with_batch: bool = True,
    with_scan: bool = True,
) -> Path:
    """Write a fake archiver checkout at ``root``; returns it.

    Each verb takes a **list** of documents, one per call in order (the last one
    repeats), so a test can drive a move — revert, then apply — through one fake.
    That is also how a **retry** is driven (#174): an ``apply`` list whose first
    document answers ``move_failed`` with the files already written and whose
    next one answers ``ok`` with ``reused: true``, which is exactly the pair the
    archiver produces when the same decision is sent a second time.
    """
    root.mkdir(parents=True, exist_ok=True)
    if with_batch:
        (root / "main_batch.py").write_text(_MAIN_BATCH, encoding="utf-8")
    if with_scan:
        (root / "main_scan.py").write_text(_MAIN_SCAN, encoding="utf-8")
    (root / "_responses.json").write_text(
        json.dumps({
            "plan": list(plan or []), "apply": list(apply or []), "revert": list(revert or []),
            "exit_code": exit_code, "scan_exit_code": scan_exit_code, "sleep": sleep,
        }),
        encoding="utf-8",
    )
    (root / "_calls.jsonl").write_text("", encoding="utf-8")
    return root


def calls(root: Path) -> list[dict[str, Any]]:
    """Every invocation the fake recorded, in order."""
    raw = (root / "_calls.jsonl").read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


__all__ = [
    "FOLDER_BILLS", "FOLDER_HOUSE", "apply_doc", "apply_result", "build_fake_archiver",
    "calls", "candidate", "error_doc", "mail", "plan_doc", "revert_doc", "revert_result",
]
