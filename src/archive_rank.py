"""The local model picks the archive folder among the suggester's candidates (#158, Step 2/3).

Step 1 (#157) files every Inbox mail into the folder email-archiver's suggester
ranks first. That suggester is a search engine: full-text match, thread
continuity, folder-name similarity. It is right first or second most of the
time, and it cannot read a mail. This module asks the local LLM hub to choose
among the folders it already ranked — with a confidence and a one-line reason —
and feeds every correction the user makes back in as a few-shot example.

Three rules the design turns on:

- **The model never names a folder.** It answers with an *index* into the
  candidate list it was given; the path is resolved here, from ``plan``'s own
  output. A model cannot invent a directory, misspell one, or reach outside the
  archive tree, because it never types a path.
- **The model never computes a date.** The sent date is in the item already and
  the archiver owns the filename. Nothing here asks for one.
- **The validator is the contract.** The hub refuses ``response_format:
  json_schema`` on the open-weight models (a grammar clash with ``<think>``), so
  the prompt asks for JSON and :func:`_validate_response` refuses anything else —
  same shape as ``src/ai/triage.py``: exact keys, every requested id exactly
  once, every index in range, confidence a real number in [0, 1].

:func:`rank` is a pure function of ``(mails, corrections, client)`` — it reads no
database and writes none — so a fake client returning canned JSON exercises the
whole path. A hub failure degrades **that batch** to the suggester's own order
with the reason recorded on every mail in it and on the run; a run never fails
because the model was unavailable.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.ai.client import AIError

logger = logging.getLogger(__name__)

#: Mails per hub request. Eight keeps one prompt well inside the model's
#: context with 20 few-shot examples attached (measured, ~6k characters).
DEFAULT_BATCH_SIZE = 8
#: Few-shot corrections carried in every prompt.
DEFAULT_EXAMPLES = 20

MAX_SUBJECT_CHARS = 160
MAX_SENDER_CHARS = 120
MAX_PREVIEW_CHARS = 400
MAX_SAMPLE_SUBJECTS = 2
MAX_SAMPLE_CHARS = 80
#: Candidates put in front of the model, out of the ``archive.candidates`` the
#: archiver ranks. The tail of that list is noise — a folder the suggester put
#: eighth is almost never the right one — and every extra candidate is prompt
#: the model has to read and reason about, which is what makes an open-weight
#: model ramble past its output budget instead of answering. Measured: 10
#: candidates × 7 mails is a 21k-character prompt whose answer did not always
#: arrive; six candidates halves it. Indices stay the archiver's own, because
#: only a prefix is dropped.
MAX_CANDIDATES_SHOWN = 6
MAX_RECIPIENTS = 3
MAX_REASON_CHARS = 240
#: Trailing folder components shown to the model — the archive tree is deep and
#: only the leaf end of a path carries meaning.
FOLDER_PARTS = 3
#: Output budget for one batch — and it is **not** the size of the answer.
#: The open-weight models on this hub emit their reasoning as ordinary output
#: tokens before the JSON and the hub drops that part, so a budget sized for
#: the picks alone comes back as an *empty* answer with ``stop_reason
#: max_tokens`` — which this module correctly reports as a batch the model did
#: not rank, but which is a waste of a minute either way. Measured over live
#: runs of a 7-mail Inbox: ``agentic_light_nothink`` spent 2238 output tokens
#: on a good answer and blew past 6000 on one run in three; plain
#: ``agentic_light`` never finished reasoning. Hence 6000 (generous for the
#: open-weight path) and ``claude_haiku`` as the configured default.
MAX_TOKENS = 6000

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_PICK_KEYS = {"message_id", "candidate", "confidence", "reason"}

SYSTEM_PROMPT = """You file emails into an existing archive folder tree.
For each mail you get the folders a search engine already ranked, numbered from 0.
Return JSON only, with this exact top-level shape:
{"picks":[{"message_id":"<id>","candidate":0,"confidence":0.82,"reason":"short explanation"}]}
Return exactly one pick for every supplied mail and no others.
candidate is the index of the folder this mail belongs in, or null when none of them fits.
Never write a folder path, never invent a folder, never propose a date: only an index.
confidence is a number from 0 to 1: how sure you are that this mail belongs there.
Prefer the folder whose past subjects and correction examples match this mail's topic,
not the one with the highest score. Keep each reason under 20 words. Do not invent facts."""


class RankClient(Protocol):
    """What :func:`rank` needs of ``src.ai.client.AIClient`` — and a fake."""

    model: str

    def complete(self, *, system: str, user: str, max_tokens: int) -> str: ...


@dataclass(frozen=True)
class Pick:
    """One mail's destination, as decided by the model or degraded to the suggester.

    ``source`` is the distinction that matters downstream: a **model** pick with
    ``candidate is None`` means *none of these folders fits* (→ the mail stays in
    the Inbox), while a **fallback** pick means the model never answered at all
    (→ the archiver's own top candidate is used, with ``reason`` saying why).
    """

    candidate: int | None
    confidence: float | None
    reason: str
    source: str  # "model" | "fallback"


@dataclass(frozen=True)
class Ranking:
    """Every mail's pick, plus what the run needs to report about the ranking."""

    picks: dict[str, Pick] = field(default_factory=dict)
    #: One entry per degraded batch — the run's ``error`` names them.
    errors: list[str] = field(default_factory=list)
    #: Mails the model actually ranked, and how many of those it filed where the
    #: suggester would have. The accept rate per run is the metric that says
    #: when the ranking can be trusted unread; agreement is what says how much
    #: of it is the model's own judgement.
    ranked: int = 0
    agreed: int = 0

    @property
    def agreement(self) -> float | None:
        """Share of ranked mails the model and the suggester agree on, or ``None``.

        ``None`` is not zero: it means the model ranked nothing this run (an
        empty Inbox, or a hub that never answered), and a run that reports 0.0
        there would read as *the model disagreed with everything*.
        """
        return (self.agreed / self.ranked) if self.ranked else None


# ------------------------------------------------------------------- prompt


def short_folder(path: str, parts: int = FOLDER_PARTS) -> str:
    """The last ``parts`` components of a folder path, separators normalised."""
    pieces = [p for p in str(path or "").replace("\\", "/").split("/") if p]
    return "/".join(pieces[-parts:]) if pieces else ""


def format_correction(correction: dict[str, Any]) -> str:
    """One stored correction as the few-shot line the prompt carries."""
    subject = str(correction.get("subject") or "")[:MAX_SUBJECT_CHARS]
    sender = str(correction.get("sender") or "")[:MAX_SENDER_CHARS]
    suggested = short_folder(str(correction.get("suggested_folder") or ""))
    chosen = short_folder(str(correction.get("chosen_folder") or ""))
    hint = str(correction.get("hint") or "").strip()[:MAX_REASON_CHARS]
    line = f'mail "{subject}" from {sender} → suggested {suggested or "nothing"}, chosen {chosen}'
    return f"{line}, hint: {hint}" if hint else line


def shown_candidates(mail: dict[str, Any]) -> list[dict[str, Any]]:
    """The candidates this mail's prompt shows — the head of the archiver's list.

    The one place the cut is made, so the prompt and the validator's range check
    can never disagree about which indices exist.
    """
    ranked = [c for c in (mail.get("candidates") or []) if isinstance(c, dict)]
    return ranked[:MAX_CANDIDATES_SHOWN]


def _mail_context(mail: dict[str, Any]) -> dict[str, Any]:
    """One mail, bounded, with its candidates as an indexed list."""
    candidates = []
    for index, candidate in enumerate(shown_candidates(mail)):
        samples = [
            str(s)[:MAX_SAMPLE_CHARS]
            for s in (candidate.get("sample_subjects") or [])[:MAX_SAMPLE_SUBJECTS]
        ]
        candidates.append({
            "index": index,
            "folder": short_folder(str(candidate.get("folder_path") or "")),
            "score": round(float(candidate.get("score") or 0.0), 3),
            "matches": int(candidate.get("match_count") or 0),
            "samples": samples,
        })
    return {
        "message_id": str(mail.get("message_id") or ""),
        "subject": str(mail.get("subject") or "")[:MAX_SUBJECT_CHARS],
        "from": str(mail.get("sender") or "")[:MAX_SENDER_CHARS],
        "to": [str(r)[:MAX_SENDER_CHARS] for r in (mail.get("recipients") or [])[:MAX_RECIPIENTS]],
        "sent": str(mail.get("date_sent") or ""),
        "preview": str(mail.get("body_preview") or "")[:MAX_PREVIEW_CHARS],
        "attachments": int(mail.get("attachment_count") or 0),
        "candidates": candidates,
    }


def build_prompt(mails: list[dict[str, Any]], corrections: list[dict[str, Any]]) -> str:
    """The user half of one batch request — deterministic, bounded, JSON."""
    return json.dumps(
        {
            "corrections": [format_correction(c) for c in corrections],
            "mails": [_mail_context(m) for m in mails],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


# ---------------------------------------------------------------- validation


def _json_text(raw: str) -> str:
    text = (raw or "").strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _invalid(detail: str) -> AIError:
    return AIError(
        "ai_invalid_response", "the local model returned an unusable ranking",
        http_status=502, detail=detail,
    )


def _validate_response(raw: str, expected: dict[str, int]) -> dict[str, Pick]:
    """The model's answer, or ``AIError`` — nothing in between.

    ``expected`` maps every requested ``message_id`` to how many candidates that
    mail had, which is what makes an out-of-range index a *loud* failure rather
    than a mail filed into whichever folder the index happened to land on.
    """
    try:
        decoded = json.loads(_json_text(raw))
    except ValueError as exc:
        raise _invalid(f"invalid JSON: {exc}") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"picks"}:
        raise _invalid("response must contain exactly the picks key")
    picks = decoded["picks"]
    if not isinstance(picks, list):
        raise _invalid("picks is not a list")

    seen: dict[str, Pick] = {}
    for item in picks:
        if not isinstance(item, dict) or set(item) != _PICK_KEYS:
            raise _invalid("every pick must contain exactly the documented keys")
        message_id = item["message_id"]
        if not isinstance(message_id, str) or message_id not in expected:
            raise _invalid("a pick names a mail that was not in this batch")
        if message_id in seen:
            raise _invalid(f"two picks for the same mail ({message_id})")
        candidate = item["candidate"]
        if candidate is not None:
            if not isinstance(candidate, int) or isinstance(candidate, bool):
                raise _invalid(f"candidate for {message_id} is not an index")
            if not 0 <= candidate < expected[message_id]:
                raise _invalid(
                    f"candidate {candidate} for {message_id} is outside its "
                    f"{expected[message_id]} candidates"
                )
        confidence = item["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise _invalid(f"confidence for {message_id} is not a number")
        if not 0.0 <= float(confidence) <= 1.0:
            raise _invalid(f"confidence {confidence} for {message_id} is outside 0..1")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise _invalid(f"missing reason for {message_id}")
        seen[message_id] = Pick(
            candidate=candidate,
            confidence=float(confidence),
            reason=reason.strip()[:MAX_REASON_CHARS],
            source="model",
        )
    if set(seen) != set(expected):
        raise _invalid("the picks do not cover exactly the mails in this batch")
    return seen


# -------------------------------------------------------------------- rank


def _batches(mails: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    step = max(1, int(size))
    return [mails[i:i + step] for i in range(0, len(mails), step)]


def rank(
    mails: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    client: RankClient,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Ranking:
    """Ask the model to pick a folder for every mail that has candidates.

    Pure: no database, no filesystem, no Outlook. Mails without candidates are
    not sent (there is nothing to choose between) and get no pick, which leaves
    them exactly where Step 1 left them — ``needs_review``.
    """
    eligible = [m for m in mails if not m.get("already_archived") and shown_candidates(m)]
    if not eligible:
        return Ranking()

    picks: dict[str, Pick] = {}
    errors: list[str] = []
    ranked = agreed = 0
    for batch in _batches(eligible, batch_size):
        expected = {str(m.get("message_id") or ""): len(shown_candidates(m)) for m in batch}
        started = time.monotonic()
        try:
            raw = client.complete(
                system=SYSTEM_PROMPT,
                user=build_prompt(batch, corrections),
                max_tokens=MAX_TOKENS,
            )
            decided = _validate_response(raw, expected)
        except AIError as exc:
            # One batch degrades; the run still completes. The reason rides
            # every mail in it *and* the run, because "filed by the archiver's
            # own ranking" is a different fact from "the model chose this".
            note = (
                f"the local model could not rank this batch ({exc.code}) — the archiver's "
                "own ranking was used"
            )
            errors.append(f"{exc.code}: {exc}" + (f" ({exc.detail})" if exc.detail else ""))
            for message_id in expected:
                picks[message_id] = Pick(None, None, note, "fallback")
            logger.warning(
                "⚠️ archive rank: %d mail(s) fell back to the archiver — %s: %s",
                len(expected), exc.code, exc.detail or exc,
            )
            continue

        batch_agreed = sum(1 for p in decided.values() if p.candidate == 0)
        ranked += len(decided)
        agreed += batch_agreed
        picks.update(decided)
        logger.info(
            "ℹ️ archive rank: %d mail(s), %d agreed with the archiver, %.1f s via %s",
            len(decided), batch_agreed, time.monotonic() - started,
            getattr(client, "model", None) or "the configured model",
        )
    return Ranking(picks=picks, errors=errors, ranked=ranked, agreed=agreed)


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_EXAMPLES",
    "MAX_CANDIDATES_SHOWN",
    "MAX_TOKENS",
    "SYSTEM_PROMPT",
    "Pick",
    "RankClient",
    "Ranking",
    "build_prompt",
    "format_correction",
    "rank",
    "short_folder",
    "shown_candidates",
]
