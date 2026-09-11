"""The spoken sentence becomes a title and a description (#147).

A sentence you say carries more than a title. *"Urgent, I need to call the
plumber about the leaking radiator in the guest room before Friday"* is a
title, a description and a due date; :mod:`src.quick_add` is a deliberately
narrow regex parser (a trailing date phrase, ``#id`` / ``> title`` for a
parent, nothing else), so all of it became one long title. This module sends
the finished transcript to the hub's light model and splits it.

**Voice only.** ``POST /api/parse``, the typed quick-add line and the CLI are
untouched, so "the CLI and the UI agree on what a phrase means" still holds
for everything typed — and typing keeps its instant, deterministic preview
instead of waiting on a model.

**The model is named here**, unlike transcription (#144), which names none so
the hub can apply its ``roles.audio.transcribe`` role. There is no text role
to defer to, and the choice is load-bearing:

    ``agentic_light`` cannot do schema-constrained decoding on this backend.
    Probed live 2026-09-07: an OpenAI ``response_format: json_schema`` request
    comes back **400** — *"Failed to initialize samplers: Unexpected empty
    grammar stack after accepting piece: <think>"*. Its chat template injects
    a thinking prefix the grammar cannot accommodate, and
    ``agentic_light_nothink`` (the same llama-server) fails identically.

So the JSON is asked for in the prompt and *validated* here rather than
constrained upstream: the reply is stripped of any ``<think>`` block and any
code fence, parsed, and read through an allow-list. Anything else is a
fallback, never a crash. Warm, the round trip measured **1.55 s**.

**A date only if you said one — enforced, not requested.** The same probe
asked for *"before friday"* with today = Monday 2026-09-07 and got
``2026-09-13``: a **Sunday**. Friday was the 11th. A model that cannot count
days must not be the thing that sets a due date, so it may only quote a
*phrase*, and two guards stand behind that:

    1. the phrase must appear **verbatim** (case-insensitively) in the
       transcript, or it is dropped — that is what stops an invented date;
    2. :func:`src.dates.parse_date` resolves it, never the model.

A model that returns a resolved ISO date instead of a phrase has that date
discarded. The cost of both guards is a date occasionally missed; the cost of
neither is a task confidently due on the wrong day.

**Failure is a state, not an exception.** Every way this can go wrong — no
``enrich.url``, the hub down, a timeout, a refusal, junk instead of JSON —
comes back as the ordinary :func:`src.quick_add.parse` answer with
``source: "parser"`` and a reason. The transcript is already on screen by
then; losing the tidy-up must not look like a broken microphone. ``source``
is never omitted and never guessed: it says which of the two actually
produced what you are reading.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from src import clock, quick_add
from src.config import AppConfig
from src.dates import DateParseError, parse_date
from src.voice import connect_failure, endpoint_of

logger = logging.getLogger(__name__)

#: Same shape and reasoning as ``src.voice``'s probe — whose connect this
#: reuses, timeout included: a cached TCP connect, so opening the dialog
#: repeatedly costs one connect and starting the hub shows up on the next open.
PROBE_TTL_S = 15.0
#: Warm this is ~1.5 s; a cold model load took 4.4 s in the probe. Generous
#: enough for a cold one, short enough that a wedged hub does not hold the
#: dialog's "tidying…" state for a minute.
DEFAULT_TIMEOUT_S = 30.0
#: A quick-add line, not an essay — and a bound on what a runaway model can
#: cost. Roughly two paragraphs of description.
MAX_TOKENS = 400
#: Nothing worth enriching is shorter, and it keeps a stray tap off the hub.
MIN_TEXT_CHARS = 12
#: Trimmed into the reason so a refusal says what the endpoint said.
_UPSTREAM_BODY_CHARS = 200

#: Which of the two produced the answer. Never omitted, never inferred.
LLM = "llm"
PARSER = "parser"

#: The only keys read off the model's reply. Anything else it invents is
#: ignored rather than trusted — the form has no field for it, and a key we do
#: not know is not a key we can validate.
_ALLOWED = ("title", "description", "due_phrase", "starts_phrase")

#: Qwen-family templates emit a thinking block before the answer.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
#: ```json … ``` — the other thing a chat model wraps JSON in.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

_SYSTEM = (
    "You turn a short spoken note into one task. Today is {today} ({weekday}).\n"
    "Reply with JSON only — no prose, no code fence — with exactly these keys:\n"
    '  "title"         a short imperative task title, no date words in it\n'
    '  "description"   the remaining detail, or "" if the note has none\n'
    '  "due_phrase"    the words in the note that say WHEN it is due, copied\n'
    "                  verbatim from the note (e.g. \"before friday\", \"next\n"
    '                  week"), or null if the note names no deadline\n'
    '  "starts_phrase" the same for when work should START, or null\n'
    "Never compute or invent a date: copy the words, or answer null. Never put\n"
    "a date in the title. Do not add anything the note does not say."
)


class EnrichError(RuntimeError):
    """The enrichment could not happen; ``reason`` is the sentence to record.

    Deliberately *not* surfaced to the caller as an HTTP failure the way
    :class:`src.voice.VoiceError` is — enrichment is a tidy-up on top of an
    answer that already exists, so the route catches this and falls back.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def strip_wrappers(raw: str) -> str:
    """The JSON inside a chat model's answer: thinking block and fence removed.

    Both are things the model adds around the payload rather than to it, and
    both are why ``response_format`` could not be used here (see the module
    docstring) — so they are handled where they land instead.
    """
    text = _THINK_RE.sub("", raw or "").strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    # An unfenced reply that still has a preamble: take the outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        return text[start:end + 1]
    return text


def resolve_phrase(phrase: Any, transcript: str, today: date) -> tuple[str | None, str | None]:
    """``(iso, phrase)`` for a date the note actually named — else ``(None, None)``.

    Both guards live here, because both are the same rule seen twice: the
    model may point at words, and only :mod:`src.dates` may turn words into a
    day.

    A phrase that is not in the transcript is a phrase nobody said. That is the
    guard that matters: a model asked for "the words that say when" will
    happily answer with a date it worked out instead, and a wrong day is worse
    than no day because nothing about it looks wrong later.
    """
    if not isinstance(phrase, str):
        return None, None
    cleaned = phrase.strip().strip(".,;:!?")
    if not cleaned:
        return None, None
    if cleaned.lower() not in transcript.lower():
        logger.info("ℹ️ enrich: dropped %r — not said in the transcript", cleaned)
        return None, None
    try:
        # `strip_lead_in` is quick_add's, not a second copy: asked for "the
        # words that say when", a model answers with the preposition attached
        # ("before friday"), which is exactly what a typed line does too.
        d = parse_date(quick_add.strip_lead_in(cleaned), today=today)
    except DateParseError:
        # The words were said but they are not a date this app understands.
        # No date is the honest answer; the words stay in the title.
        return None, None
    if d is None:  # "none" / "clear" — the no-date literals, not a date phrase
        return None, None
    return d.isoformat(), cleaned


class EnrichClient:
    """The install's text model: whether it is there, and what it made of a line.

    Built once in the webapp lifespan (``app.state.enrich``). No thread and no
    background work — a cached probe and one POST, the same shape as
    :class:`src.voice.VoiceClient`.
    """

    def __init__(self, config: AppConfig) -> None:
        self.url = (config.enrich.url or "").strip()
        self.model = (config.enrich.model or "").strip()
        self.timeout = float(config.enrich.timeout_seconds or DEFAULT_TIMEOUT_S)
        self._lock = threading.Lock()
        self._verdict: tuple[float, bool, str | None] | None = None
        self._checked_at: str | None = None

    # ------------------------------------------------------------- config
    @property
    def unconfigured_reason(self) -> str | None:
        """Why this install cannot enrich at all — ``None`` when it can."""
        if not self.url:
            return "no enrich.url in config"
        if endpoint_of(self.url) is None:
            return f"enrich.url is not an http(s) URL: {self.url}"
        if not self.model:
            return "no enrich.model in config"
        return None

    # -------------------------------------------------------------- probe
    def probe(self, *, force: bool = False) -> tuple[bool, str | None]:
        """``(reachable, reason)`` — a cached connect. Never raises."""
        reason = self.unconfigured_reason
        if reason:
            return False, reason
        with self._lock:
            cached = self._verdict
            if cached and not force and time.monotonic() < cached[0]:
                return cached[1], cached[2]
        failure = connect_failure(self.url)
        with self._lock:
            self._verdict = (time.monotonic() + PROBE_TTL_S, failure is None, failure)
            self._checked_at = clock.now_iso()
        return failure is None, failure

    def status(self) -> dict[str, Any]:
        """``/api/status``'s ``enrich`` key — what Settings and the CLI read."""
        reachable, reason = self.probe()
        return {
            "enabled": reachable,
            "reason": None if reachable else reason,
            "url": self.url,
            "model": self.model,
            "checked_at": self._checked_at,
        }

    # ------------------------------------------------------------- enrich
    def fields(self, text: str, *, today: date) -> dict[str, Any]:
        """``{title, description, due_phrase, starts_phrase}`` from the model.

        Raises :class:`EnrichError` for every way this can fail, so the caller
        has exactly one thing to catch and one reason to record.
        """
        reason = self.unconfigured_reason
        if reason:
            raise EnrichError(reason)
        note = (text or "").strip()
        if len(note) < MIN_TEXT_CHARS:
            raise EnrichError(f"nothing to enrich — {len(note)} characters")

        payload = json.dumps({
            "model": self.model,
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": _SYSTEM.format(
                    today=today.isoformat(), weekday=today.strftime("%A"),
                )},
                {"role": "user", "content": note},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as res:
                body = res.read()
                served = res.headers.get("x-hub-served-model")
        except urllib.error.HTTPError as exc:
            said = exc.read().decode("utf-8", errors="replace").strip()[:_UPSTREAM_BODY_CHARS]
            raise EnrichError(f"the model refused the request (HTTP {exc.code}): "
                              f"{said or '(no body)'}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            with self._lock:            # it just proved itself unreachable
                self._verdict = None
            raise EnrichError(f"{self.url} did not answer — "
                              f"{exc.__class__.__name__}: {exc}") from exc

        try:
            content = json.loads(body)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise EnrichError(f"the model's answer was not a chat completion: {exc}") from exc
        try:
            parsed = json.loads(strip_wrappers(content))
        except ValueError as exc:
            raise EnrichError(f"the model did not answer with JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise EnrichError(f"the model answered a {type(parsed).__name__}, not an object")

        logger.info(
            "ℹ️ enrich: %d chars → %s in %.1f s via %s",
            len(note), ", ".join(k for k in _ALLOWED if parsed.get(k)) or "nothing",
            time.monotonic() - started, served or self.model,
        )
        return {k: parsed.get(k) for k in _ALLOWED}


def enrich_line(
    client: EnrichClient | None, text: str, *, today: date | None = None,
) -> dict[str, Any]:
    """One spoken line → the quick-add fields, however far we got.

    Always answers, and always says which of the two answered. The
    deterministic :func:`src.quick_add.parse` runs first and is the floor: the
    model can only replace the title, add a description and point at dates.
    ``parent_ref`` stays the parser's, because ``#12`` and ``› garden-bot`` are
    syntax, not language — the model was never asked about them.
    """
    today = today or clock.today()
    base = quick_add.parse(text, today)
    out: dict[str, Any] = {
        **base, "description": "", "source": PARSER, "model": None, "reason": None,
    }
    if client is None:
        out["reason"] = "enrichment service not started"
        return out
    try:
        fields = client.fields(text, today=today)
    except EnrichError as exc:
        logger.info("ℹ️ enrich: falling back to the parser — %s", exc.reason)
        out["reason"] = exc.reason
        return out

    title = (fields.get("title") or "").strip()
    description = (fields.get("description") or "").strip()
    due, due_phrase = resolve_phrase(fields.get("due_phrase"), text, today)
    starts, starts_phrase = resolve_phrase(fields.get("starts_phrase"), text, today)
    # An empty title is the one thing that cannot be used — the line has to say
    # something. Everything else degrades to the parser's answer field by field.
    if not title:
        out["reason"] = "the model returned no title"
        return out
    out.update({
        "title": title,
        "description": description,
        "due": due if due is not None else base["due"],
        "due_phrase": due_phrase if due is not None else base["due_phrase"],
        "starts": starts if starts is not None else base["starts"],
        "starts_phrase": starts_phrase if starts is not None else base["starts_phrase"],
        "source": LLM,
        "model": client.model,
    })
    return out
