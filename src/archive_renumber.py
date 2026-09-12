"""Healing the stored paths an archiver renumber renamed (#176, split out in #186).

The archiver re-sequences a folder's ``NNN`` prefixes after ``apply`` and
``revert`` (email-archiver#61) and hands back a ``renumbered`` map; this module
turns that map into the three ``UPDATE``s that keep task-os's own copies of those
paths true. It is a function of one JSON document and a connection — no
subprocess, no service state — so ``src/archive_batch.py`` calls into it after
each verb and ``scripts/apply_renumber_map.py`` calls it on a saved map, and
neither has to reach it through the other. Nothing here imports
``archive_batch``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from src import archive_rank, email_capture, placeholders

logger = logging.getLogger(__name__)


def last_component(folder: str) -> str:
    """The folder's own name — what the reason line names it by."""
    return archive_rank.short_folder(folder, 1)


def loads(raw: Any, default: Any) -> Any:
    """One JSON column's value, or ``default`` when it is empty or unreadable.

    A row whose JSON a past bug left unparseable still renders — as the empty
    list its column means — with the warning saying which column it was.
    """
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("⚠️ archive: unreadable JSON column — falling back to %r", default)
        return default


# ------------------------------------------------------------- renumbering
# The archiver re-sequences a folder after the two verbs that disturb it, so
# its ``NNN`` prefixes stay contiguous and in sent-date order
# (email-archiver#61) — ``revert`` leaves a hole, ``apply`` always allocates
# ``max + 1``. That renames files **this** database holds paths to, and the
# archiver heals only its own index: "the consumer must heal its stored paths
# from the map" is its contract, and this is that heal. Three places store a
# ``.msg`` path here — ``archive_items.files_json``, an email link's ref and a
# captured task's ``external_id`` — and all three follow the map or a revert
# deletes the wrong file, a chip goes dead and the next capture poll lands the
# same mail again under its new name.
#
# The map is **additive** on the archiver's side (no ``schema_version`` bump),
# so a build without it simply reports nothing and every reader below treats
# absence as "nothing moved" rather than as an error.


def renumber_pairs(entries: Any) -> list[tuple[str, str]]:
    """Every ``old → new`` rename in one folder's map entries, read defensively.

    An entry is ``{"from", "to", "message_id", "attachments": [[old, new], …]}``
    and only bundles that actually changed appear. ``from``/``to`` are ``None``
    for a bundle carrying no ``.msg`` at all (its files are all attachments), so
    a pair is taken only when both sides name something; anything else shaped
    unexpectedly is skipped rather than guessed at.
    """
    pairs: list[tuple[str, str]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        old, new = entry.get("from"), entry.get("to")
        if old and new:
            pairs.append((str(old), str(new)))
        for attachment in entry.get("attachments") or []:
            if isinstance(attachment, (list, tuple)) and len(attachment) == 2 and all(attachment):
                pairs.append((str(attachment[0]), str(attachment[1])))
    return pairs


def renumbered_folders(doc: Any) -> dict[str, list[Any]]:
    """One verb document's ``renumbered`` map — ``{}`` when it carries none.

    A folder the archiver could **not** renumber is never an empty list in here
    (an empty list means "already in order"): it is named under
    ``renumber_refused`` with a reason, which is logged rather than folded into
    the quiet path — "nothing to do" and "this folder was left alone" are two
    different facts, and only the second one may leave a stored path stale.
    """
    if not isinstance(doc, dict):
        return {}
    for refused in doc.get("renumber_refused") or []:
        if isinstance(refused, dict):
            logger.warning(
                "⚠️ archive: the archiver refused to renumber %s — %s",
                last_component(str(refused.get("folder_path") or "an unnamed folder")),
                refused.get("reason") or "no reason given",
            )
    mapping = doc.get("renumbered")
    if not isinstance(mapping, dict):
        return {}
    return {str(k): v for k, v in mapping.items() if isinstance(v, list)}


def rename_index(doc: Any) -> dict[str, str]:
    """``{normalised old path: the new path, verbatim}`` over a whole document.

    Keyed on the normalised, case-folded path because the archiver reports
    Windows paths with backslashes and a stored one may have been normalised on
    the way in; the **value** is kept exactly as the archiver wrote it, which is
    the form a fresh ``apply`` would have stored.
    """
    index: dict[str, str] = {}
    for entries in renumbered_folders(doc).values():
        for old, new in renumber_pairs(entries):
            index[placeholders.normalize_path(old).casefold()] = new
    return index


def rename_files(files: list[str], index: dict[str, str]) -> list[str]:
    """A result's own ``files`` list through the map — the archiver's own caveat.

    An ``apply --renumber`` result reports each mail's files under the names it
    **wrote** them with, and the renumber that ran afterwards may already have
    moved some of them. So the map applies to the same document's results
    before they are stored, or ``files_json`` records a name that no longer
    exists and a later ``revert`` is handed it.
    """
    return [index.get(placeholders.normalize_path(f).casefold(), f) for f in files]


def apply_renumber_map(
    conn: sqlite3.Connection,
    folder: str,
    entries: Any,
    *,
    placeholders_map: Any = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Heal every stored path one folder's renumber renamed; the counts per table.

    ``entries`` is that folder's list from the ``renumbered`` map. Returns
    ``{"renames", "items", "links", "tasks"}`` — the renames the map describes,
    then the rows actually rewritten in each of the three places. ``dry_run``
    computes exactly the same counts and writes nothing, which is what
    ``scripts/apply_renumber_map.py --dry-run`` previews against the live
    database before it is asked to touch it.

    **Idempotent by construction**: a pair whose old path is no longer stored
    anywhere matches nothing, so re-running a map is a no-op and a heal
    interrupted half-way is finished simply by running it again.
    """
    pairs = renumber_pairs(entries)
    counts = {"renames": len(pairs), "items": 0, "links": 0, "tasks": 0}
    if not pairs:
        return counts
    renames = {placeholders.normalize_path(old).casefold(): new for old, new in pairs}

    for row in conn.execute(
        "SELECT id, files_json FROM archive_items WHERE files_json IS NOT NULL"
    ).fetchall():
        files = [str(f) for f in loads(row["files_json"], [])]
        healed = rename_files(files, renames)
        if healed == files:
            continue
        counts["items"] += 1
        if not dry_run:
            conn.execute(
                "UPDATE archive_items SET files_json = ? WHERE id = ?",
                (json.dumps(healed, ensure_ascii=False), int(row["id"])),
            )

    known = dict(placeholders_map or {})
    for old, new in pairs:
        moved = email_capture.rename_ref(
            conn,
            placeholders.to_ref(placeholders.normalize_path(old), known),
            placeholders.to_ref(placeholders.normalize_path(new), known),
            dry_run=dry_run,
        )
        counts["links"] += moved["links"]
        counts["tasks"] += moved["tasks"]

    if not dry_run:
        conn.commit()
    logger.info(
        "ℹ️ archive: %s %d renamed file(s) in %s — %d item(s), %d link(s), %d captured task(s)",
        "would heal" if dry_run else "healed", counts["renames"], last_component(folder),
        counts["items"], counts["links"], counts["tasks"],
    )
    return counts
