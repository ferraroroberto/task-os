"""Voice quick-add — a recorded phrase becomes a quick-add line, locally (#92).

Hold the mic on the quick-add bar, say *"buy a new filter for the dehumidifier
next week"*, let go: the clip goes to the fleet's whisper server and the
transcript comes back through the ordinary ``src.quick_add`` parse, so the
chips preview is the one you would have got by typing. Nothing leaves the
house — the audio's whole journey is browser → task-os → ``127.0.0.1:8090``.

**The phone never talks to whisper.** It reaches this app over the one
Tailscale HTTPS endpoint with the cookie gate (``src.auth``) and could not
open ``:8090`` if it tried; ``POST /api/transcribe`` forwarding server-side is
what makes voice work off-PC at all.

**WAV in, always — verified, not assumed.** whisper.cpp's ``whisper-server``
decodes WAV and answers a bare ``400 Invalid request`` to anything else; a
probe against the live ``:8090`` (2026-09-07) took ``200`` for a 16 kHz WAV
and ``400`` for both browser recording formats — webm/opus (Chrome) and
mp4/aac (iOS Safari). So ``static/voice.js`` decodes its own recording and
re-encodes it as 16 kHz mono PCM WAV *before* the upload, and this module is
what the issue asked for and nothing more: a plain HTTP forward, no
subprocess, no transcoding, no dependency. An endpoint that refuses the body
comes back as a 502 naming the upstream status and what was sent, never an
opaque failure.

:class:`VoiceClient` is built once in the webapp lifespan (``app.state.voice``)
and by the CLI's offline status. It has no thread and no background work —
only two things happen here:

    probe()       a TCP connect to the endpoint's host/port, cached for
                  :data:`PROBE_TTL_S`. Port 8090 is mutex-shared with
                  ``automation/audio/transcribe_voice``, so a mic button
                  rendered on every dialog open must not hammer it. "Reachable"
                  is exactly what a connect establishes — that the port
                  answered, not that a transcription will succeed, which
                  reports its own failure on its own.
    transcribe()  one multipart POST of the clip, returning the text —
                  trimmed of the trailing full stop whisper punctuates every
                  dictated line with, which the quick-add parse would
                  otherwise read as part of the date phrase.

``status()`` is what ``GET /api/status``'s ``voice`` key, the Settings card,
the mic button's hint and ``tasks mirror status`` all render — off always
carries its reason, never an empty result.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from src import clock
from src.config import AppConfig

logger = logging.getLogger(__name__)

#: How long a reachability verdict is trusted before the port is touched again.
#: Long enough that opening the quick-add dialog repeatedly costs one connect,
#: short enough that starting whisper shows up on the next open.
PROBE_TTL_S = 15.0
#: Generous for a loopback connect on purpose. The verdict is cached and the
#: mic is disabled until it lands, so a slow probe costs a moment of "checking"
#: — while a probe that gives up too early costs a *wrong* "not reachable" on
#: an endpoint that is simply on another machine.
PROBE_TIMEOUT_S = 1.5
#: A phrase is seconds of speech, but a cold model on CPU is slow to answer.
TRANSCRIBE_TIMEOUT_S = 120.0
#: 16 kHz mono PCM is 32 KB/s, so this is ~13 minutes — far past a quick-add
#: line and still small enough that a stuck recorder cannot exhaust memory.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
#: What the browser is asked to send and what whisper-server can read.
AUDIO_CONTENT_TYPE = "audio/wav"
#: Trimmed into the 502's detail so a rejection says what the endpoint said.
_UPSTREAM_BODY_CHARS = 300


class VoiceError(RuntimeError):
    """A transcription that could not happen, carrying the reason to show.

    ``code`` is the JSON envelope's error code and ``http_status`` the answer
    the route gives — the two conditions are deliberately distinct: an
    endpoint that never answered (503, "not reachable") is not an endpoint
    that refused the body (502, "rejected it, and here is what it said").
    """

    def __init__(self, message: str, *, code: str, http_status: int, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.detail = detail


def endpoint_of(url: str) -> tuple[str, int] | None:
    """``(host, port)`` to connect to — ``None`` when *url* is not addressable."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:      # a non-numeric port in the URL
        return None
    return parts.hostname, port


def build_multipart(
    audio: bytes,
    *,
    filename: str,
    content_type: str,
    fields: Mapping[str, str] | None = None,
) -> tuple[bytes, str]:
    """``(body, content_type_header)`` for one ``multipart/form-data`` upload.

    Hand-rolled on purpose: the whole outbound need is one file part plus a
    couple of scalars, and the app has no HTTP client dependency to add one
    for (``urllib`` is what every other outbound call here uses).
    """
    boundary = "taskos-" + uuid.uuid4().hex
    sep = f"--{boundary}\r\n".encode()
    out = bytearray()
    for name, value in (fields or {}).items():
        out += sep
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    out += sep
    out += (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    out += audio
    out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


#: Whisper punctuates what it hears — a dictated line comes back as "…next
#: week." — and ``src.quick_add`` reads the trailing words as a date phrase,
#: which "week." is not. So a spoken line would lose its due date to a full
#: stop nobody said. Trailing sentence punctuation is a transcription
#: artefact, not intent, and this is the one place that knows the text came
#: from speech: the quick-add grammar is left alone, so a *typed* "next week."
#: still means exactly what it says.
_TRAILING_PUNCTUATION = ".,;:!?…"


def clean_transcript(text: str) -> str:
    """The transcript as a quick-add line — trimmed, no trailing full stop."""
    stripped = (text or "").strip()
    cleaned = stripped.rstrip(_TRAILING_PUNCTUATION + " \t\r\n")
    # "?" on its own is a title, not punctuation to remove.
    return cleaned or stripped


def _text_of(payload: bytes) -> str:
    """The transcript out of whisper's answer — JSON ``{"text": …}`` or plain text."""
    body = payload.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(body)
    except ValueError:
        return body
    if isinstance(parsed, dict):
        return str(parsed.get("text", "")).strip()
    return body


class VoiceClient:
    """The install's one voice endpoint: is it there, and what did it hear."""

    def __init__(self, config: AppConfig) -> None:
        self.url = (config.voice.whisper_url or "").strip()
        self._lock = threading.Lock()
        #: (monotonic deadline, reachable, reason when not)
        self._verdict: tuple[float, bool, str | None] | None = None
        self._checked_at: str | None = None

    # ------------------------------------------------------------- config
    @property
    def unconfigured_reason(self) -> str | None:
        """Why this install cannot do voice at all — ``None`` when it can."""
        if not self.url:
            return "no voice.whisper_url in config"
        if endpoint_of(self.url) is None:
            return f"voice.whisper_url is not an http(s) URL: {self.url}"
        return None

    # -------------------------------------------------------------- probe
    def probe(self, *, force: bool = False) -> tuple[bool, str | None]:
        """``(reachable, reason)`` — a cached TCP connect to the endpoint.

        Never raises: an unreachable port is a state to render, not an error
        to handle. ``force`` skips the cache (the one caller is a test).
        """
        reason = self.unconfigured_reason
        if reason:
            return False, reason
        with self._lock:
            cached = self._verdict
            if cached and not force and time.monotonic() < cached[0]:
                return cached[1], cached[2]
        host, port = endpoint_of(self.url)  # type: ignore[misc]  — guarded above
        ok, why = True, None
        try:
            with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S):
                pass
        except TimeoutError:
            # A timeout does NOT establish which of the two it is, so it must
            # not claim to. Windows takes ~2 s to report a refusal on a dead
            # loopback port (measured here), which is longer than a probe the
            # UI waits on should take — so "nothing there" and "the port is
            # held but silent" (8090 is mutex-shared with
            # automation/audio/transcribe_voice) both land here, and the reason
            # names both rather than picking one.
            ok = False
            why = (f"{host}:{port} did not answer within {PROBE_TIMEOUT_S:g}s — whisper may be down, "
                   f"or the port may be busy (it is shared with the fleet's other transcriber)")
        except OSError as exc:
            # A refusal *is* established: there is nothing listening.
            ok = False
            why = f"nothing is listening on {host}:{port} ({exc.__class__.__name__}: {exc})"
        with self._lock:
            self._verdict = (time.monotonic() + PROBE_TTL_S, ok, why)
            self._checked_at = clock.now_iso()
        return ok, why

    def status(self) -> dict[str, Any]:
        """``/api/status``'s ``voice`` key — the mic button's hint, in JSON."""
        reachable, reason = self.probe()
        return {
            "enabled": reachable,
            "reason": None if reachable else reason,
            "url": self.url,
            "checked_at": self._checked_at,
        }

    # ---------------------------------------------------------- transcribe
    def transcribe(self, audio: bytes, *, content_type: str = AUDIO_CONTENT_TYPE) -> str:
        """The clip's transcript, or :class:`VoiceError` saying why not."""
        reason = self.unconfigured_reason
        if reason:
            raise VoiceError(reason, code="voice_disabled", http_status=409)
        if not audio:
            raise VoiceError("no audio in the request body", code="validation_error", http_status=422)
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError(
                f"recording is {len(audio)} bytes — the limit is {MAX_AUDIO_BYTES}",
                code="audio_too_large", http_status=413,
            )
        body, header = build_multipart(
            audio, filename="clip.wav", content_type=content_type,
            fields={"response_format": "json"},
        )
        request = urllib.request.Request(self.url, data=body, method="POST")
        request.add_header("Content-Type", header)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=TRANSCRIBE_TIMEOUT_S) as res:
                payload = res.read()
        except urllib.error.HTTPError as exc:
            said = exc.read().decode("utf-8", errors="replace").strip()[:_UPSTREAM_BODY_CHARS]
            logger.warning("⚠️ voice: %s refused the clip — HTTP %s %s", self.url, exc.code, said)
            raise VoiceError(
                f"the whisper server rejected the recording (HTTP {exc.code})",
                code="voice_rejected", http_status=502,
                detail=f"{self.url} answered {exc.code}: {said or '(no body)'} "
                       f"— sent {len(audio)} bytes of {content_type}",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Also the "busy" case: :8090 is mutex-shared with
            # automation/audio/transcribe_voice, so a holder that is not
            # answering reads exactly like one that is not there. Same
            # message, and the cached probe is what keeps this from becoming
            # a retry hammer.
            with self._lock:      # the endpoint just proved itself unreachable
                self._verdict = None
            logger.warning("⚠️ voice: %s did not answer — %s", self.url, exc)
            raise VoiceError(
                f"the whisper server did not answer at {self.url}",
                code="voice_unavailable", http_status=503,
                detail=f"{exc.__class__.__name__}: {exc}",
            ) from exc
        text = clean_transcript(_text_of(payload))
        logger.info(
            "ℹ️ voice: %d bytes of %s → %d chars in %.1f s",
            len(audio), content_type, len(text), time.monotonic() - started,
        )
        return text
