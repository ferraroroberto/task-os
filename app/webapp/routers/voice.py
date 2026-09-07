"""Voice route family — a recorded phrase becomes a quick-add line (#92, #146).

    POST /api/transcribe          the raw audio body → {text, parse: {…}} in
                                  one round trip (409 when voice is not
                                  configured, 503 when the whisper server did
                                  not answer, 502 when it answered and refused
                                  the clip)
    POST /api/transcribe?parse=0  the same, → {text} alone
    POST /api/enrich              {text} → the quick-add fields a light model
                                  made of the spoken sentence, or the
                                  deterministic parse and the reason why not

``?parse=0`` exists for the live transcript (#146): while you are still
speaking the page re-posts its growing take every ``partial_interval_seconds``,
and each of those passes wants the words and nothing else. Parsing a *partial*
would be worse than wasteful — a due date appearing and moving as the sentence
lands is noise, so the client deliberately shows none until the take is
finished. Skipping it also keeps a per-second request off the database
(``resolve_parent`` is the one query here).

The one ``async def`` here reads the body off the wire and then hands the
blocking forward to the threadpool — a transcription is the longest thing this
app ever waits on, and it must not be waited on *by the event loop*.

The body **is** the recording — no multipart, so the app needs no
``python-multipart`` and the browser posts its blob with one ``fetch``. The
``Content-Type`` header is the clip's own type and rides along to whisper
unchanged; ``static/voice.js`` always sends 16 kHz mono PCM WAV, which is the
only thing whisper.cpp's server decodes (see ``src/voice.py``).

The parse is folded in on purpose: the transcript's whole point is to become
the quick-add line, and a second ``POST /api/parse`` round trip from a phone
on the tailnet is a visible pause between letting go of the button and seeing
the chips. It is the *same* call — ``src.quick_add`` — so a spoken line and a
typed one can never disagree.

Voice's own status has no route of its own, for the reason capture's does not
(``routers/capture``): ``enabled`` / ``reason`` / ``url`` ride ``GET
/api/status`` under ``voice``, so the mic button, the Settings card and
``tasks mirror status`` all read one call.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.webapp.routers._helpers import error_response
from src import quick_add
from src.db import get_db
from src.enrich import enrich_line
from src.voice import MAX_AUDIO_BYTES, VoiceError

router = APIRouter(prefix="/api", tags=["voice"])


@router.post("/transcribe")
async def transcribe(
    request: Request,
    parse: bool = True,
    db: sqlite3.Connection = Depends(get_db),
) -> Any:
    client = getattr(request.app.state, "voice", None)
    if client is None:
        return error_response(409, "voice_disabled", "voice service not started")
    # Refuse an oversized upload before reading it into memory; the client
    # re-checks the body it actually got, because Content-Length is the
    # sender's claim, not a fact.
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        return error_response(
            413, "audio_too_large",
            f"recording is {declared} bytes — the limit is {MAX_AUDIO_BYTES}",
        )
    audio = await request.body()
    try:
        # The forward is blocking `urllib` and a cold model can take seconds
        # (`TRANSCRIBE_TIMEOUT_S` allows two minutes). On the event loop that
        # would freeze the *whole* app for the duration — the phone, the tray's
        # restart probe and /healthz included — so it goes to the threadpool,
        # which is where FastAPI already runs every `def` route in this repo.
        text = await run_in_threadpool(
            client.transcribe, audio,
            content_type=request.headers.get("content-type", "application/octet-stream"),
        )
    except VoiceError as exc:
        return error_response(exc.http_status, exc.code, str(exc), exc.detail)
    if not parse:
        return {"text": text}
    parsed = quick_add.parse(text)
    parsed["parent"] = quick_add.resolve_parent(db, parsed["parent_ref"])
    return {"text": text, "parse": parsed}



class EnrichBody(BaseModel):
    text: str
    today: str | None = None


@router.post("/enrich")
async def enrich(
    body: EnrichBody,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> Any:
    """The spoken sentence, split into the fields the form already has (#147).

    Answers **200 whatever happens**, because there is nothing here for a
    client to recover from: the transcript is already on the line by the time
    this is asked, so a hub that is down, slow or answering junk means the
    line keeps the deterministic parse — reported as ``source: "parser"``
    with the reason — rather than an error the user reads as a broken
    microphone. ``source`` is never omitted and never guessed: it names which
    of the two produced what is on screen.

    ``today`` pins the reference date (tests, a client in another zone), the
    same contract ``POST /api/parse`` has.
    """
    today = None
    if body.today:
        try:
            today = date.fromisoformat(body.today)
        except ValueError:
            return error_response(422, "validation_error",
                                  f"today must be YYYY-MM-DD (got {body.today!r})")
    client = getattr(request.app.state, "enrich", None)
    # Blocking `urllib` again, and slower than a transcription pass at its
    # worst — the event loop must not be the thing waiting on it.
    out = await run_in_threadpool(enrich_line, client, body.text, today=today)
    out["parent"] = quick_add.resolve_parent(db, out["parent_ref"])
    return out
