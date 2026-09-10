"""Project configuration — ``config/config.json`` with a committed sample twin.

The real file is gitignored (it carries this machine's paths); the committed
``config/config.sample.json`` documents every key. Loading is defensive: a
missing real file falls back to the sample so a fresh clone boots — with the
markdown mirror and the backup **off** (the sample's placeholders resolve to
a real synced folder; a checkout without its own config must never write
into it, #126) — and every key has a code-level default so a partial file
never crashes startup.

``TASKOS_CONFIG_PATH`` overrides the file location — the e2e harness points a
disposable instance at a temp copy so the gate never reads (or writes) the
real config.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"
CONFIG_SAMPLE_PATH = CONFIG_DIR / "config.sample.json"
CONFIG_PATH_ENV = "TASKOS_CONFIG_PATH"

DEFAULT_PORT = 8448

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_:.-]+)\}")


def resolve_placeholders(value: str, placeholders: Mapping[str, str]) -> str:
    """Expand ``{onedrive}``-style tokens from ``config.placeholders``.

    Unknown tokens are left verbatim so the caller can see (and report) what
    is missing — see :func:`unresolved_placeholders`. Used for the mirror /
    backup dirs here; folder refs go through ``src.placeholders`` (Step 9),
    which builds on this.
    """
    return _PLACEHOLDER_RE.sub(lambda m: str(placeholders.get(m.group(1), m.group(0))), value or "")


def unresolved_placeholders(value: str) -> list[str]:
    """The ``{tokens}`` still present after :func:`resolve_placeholders`."""
    return _PLACEHOLDER_RE.findall(value or "")


@dataclass(frozen=True)
class IssuesConfig:
    provider: str = "github"
    owner: str = "ferraroroberto"
    assignee: str = "@me"
    sync_minutes: int = 10


@dataclass(frozen=True)
class MirrorConfig:
    dir: str = "{onedrive}/task-os/mirror"
    backup_dir: str = "{onedrive}/task-os/backup"


@dataclass(frozen=True)
class SearchConfig:
    folder_roots: list[str] = field(default_factory=list)
    email_db: str = ""


@dataclass(frozen=True)
class CaptureConfig:
    """Inbound capture (#98) — things flagged elsewhere become Inbox tasks.

    The email poller reads the archiver's index through ``search.email_db``,
    the same path the emails adapter searches — one key, one file, read-only
    from here either way. ``email_poll_minutes`` ≤ 0 turns the poller off
    with that as its visible reason.
    """

    email_poll_minutes: int = 10


@dataclass(frozen=True)
class VoiceConfig:
    """Voice quick-add (#92) — where a recorded phrase goes to become text.

    Two endpoints, the pattern ``voice-transcriber`` already uses (#144):

    ``transcribe_url``  the **hub** (``local-llm-hub`` on :8000). No model is
                        named in the request, so the hub applies its
                        ``roles.audio.transcribe`` chain — parakeet on the
                        Mac's ANE first, whisper behind it — and the call
                        lands in its observability ring. Blank = voice off,
                        with that as the visible reason everywhere.
    ``fallback_url``    the local whisper-server, tried **only** when the
                        primary could not be reached at all (the hub process
                        is down). Blank = no fallback.

    The app forwards the clip server-side either way, so the phone needs
    nothing but the HTTPS endpoint it already has.

    ``partial_interval_seconds`` is how often the page re-posts the take it has
    accumulated so far, so the transcript appears *while* you speak (#146).
    Every pass transcribes the whole recording again — that is what
    ``voice-transcriber``'s rolling worker does too, and it is affordable
    because parakeet answers a short clip in a fraction of a second. ``0``
    turns partials off: one transcription on stop, as #92 shipped.
    """

    transcribe_url: str = "http://127.0.0.1:8000/v1/audio/transcriptions"
    fallback_url: str = "http://127.0.0.1:8090/v1/audio/transcriptions"
    partial_interval_seconds: float = 1.5


@dataclass(frozen=True)
class EnrichConfig:
    """Turning a spoken sentence into title + description (#147).

    ``url``    the hub's OpenAI-shape chat endpoint. Blank = enrichment off,
               with that as the visible reason; the transcript still lands and
               still gets the deterministic quick-add parse.
    ``model``  named on purpose, unlike transcription. ``agentic_light`` and
               ``agentic_light_nothink`` are the same llama-server here and
               both reject schema-constrained decoding (their template injects
               a ``<think>`` prefix the grammar cannot accommodate), so the
               JSON is asked for in the prompt and validated in
               :mod:`src.enrich` instead.
    """

    url: str = "http://127.0.0.1:8000/v1/chat/completions"
    model: str = "agentic_light_nothink"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AIConfig:
    """Staged AI inbox triage (#95) through the local LLM hub.

    ``enabled`` is the explicit off switch. ``base_url`` is the hub root used
    by the Anthropic SDK; ``model`` is deliberately configuration, never a
    client constant, because the hub's model catalogue changes independently
    of task-os.
    """

    enabled: bool = True
    base_url: str = "http://127.0.0.1:8000"
    model: str = "claude_haiku"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ArchiveConfig:
    """Batch archiving of the Outlook Inbox through email-archiver (#157).

    task-os never imports the archiver: it spawns that repo's ``main_batch.py``
    in the archiver's own venv and reads one JSON document back, so a hung
    Outlook COM call is a timed-out child rather than a blocked webapp.

    ``repo``     the email-archiver checkout. Blank = the feature is off, with
                 that as the visible reason. Deliberately **not** derived from
                 ``search.email_db``: the index may legitimately live elsewhere.
    ``python``   the interpreter to spawn it with. Blank = ``<repo>/.venv/
                 Scripts/python.exe`` on Windows, ``<repo>/.venv/bin/python``
                 elsewhere — the archiver's own venv, never task-os's.
    ``candidates``            ranked folders ``plan`` reports per mail.
    ``confidence_threshold``  a mail whose best candidate scores below this
                 stays in the Inbox as *needs you* (the archiver blends its
                 score into [0, 1]).
    ``timeout_seconds``       bound on one child; a full-Inbox ``plan`` walks
                 every mail over COM, so this is minutes, not seconds.
    ``enabled``  the explicit off switch, and **false in the committed
                 sample**: no checkout without its own config — a fresh clone,
                 a worktree, the disposable e2e instance — may drive the real
                 Outlook.
    ``renumber`` ask the archiver to re-sequence every folder an ``apply`` or a
                 ``revert`` disturbed, so its ``NNN`` prefixes stay contiguous
                 and in sent-date order (email-archiver#61). On by default: the
                 renaming is the archiver's own repair of a folder *this* app's
                 filing broke, and every path it renames is healed here from
                 the map it returns (:func:`~src.archive_batch.apply_renumber_map`).
                 Off leaves both verbs behaving exactly as they did.

    The ranking (#158) reaches the same hub ``ai.base_url`` names, with its own
    model: ``model`` is deliberately not ``ai.model``, because triage and
    archiving are different jobs and may want different models — and a second
    :class:`~src.ai.client.AIClient` bound to it means the triage lock and this
    one never serialise each other. ``batch_size`` is the mails per hub
    request, ``examples`` the stored corrections carried as few-shot lines.
    ``ai_timeout_seconds`` is that request's own bound: ranking a batch is
    minutes-scale work next to a triage (measured 29–64 s for 7 mails), so the
    30 s of ``ai.timeout_seconds`` would classify a working model as a dead hub.

    The default model is ``claude_haiku`` on measurement, not on taste: over
    three live runs of the same 7-mail Inbox it answered validly 3/3 (29–60 s),
    while ``agentic_light_nothink`` answered 2/3 — an open-weight model emits
    its reasoning as output tokens and sometimes never reaches the JSON — and
    plain ``agentic_light`` never finished reasoning inside any sane budget.
    Both remain one config edit away for an install that wants to stay
    entirely local.
    """

    enabled: bool = False
    repo: str = ""
    python: str = ""
    candidates: int = 10
    confidence_threshold: float = 0.7
    timeout_seconds: float = 600.0
    model: str = "claude_haiku"
    batch_size: int = 8
    examples: int = 20
    ai_timeout_seconds: float = 180.0
    renumber: bool = True


@dataclass(frozen=True)
class TeamConfig:
    enabled: bool = False
    people: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuthConfig:
    """Non-loopback access (Step 7). ``token`` is the bearer secret
    ``scripts/gen_token.py`` writes; ``password_hash`` the optional memorable
    alternative ``scripts/set_password.py`` stores (PBKDF2, never plaintext).
    Both empty (the committed sample) = only this PC can use the app."""

    token: str = ""
    password_hash: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class AppConfig:
    site: str = "home"
    port: int = DEFAULT_PORT
    issues: IssuesConfig = field(default_factory=IssuesConfig)
    placeholders: dict[str, str] = field(default_factory=dict)
    web_roots: dict[str, str] = field(default_factory=dict)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    enrich: EnrichConfig = field(default_factory=EnrichConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    source_path: Path | None = None


def config_path() -> Path:
    """The config file this process reads: env override → real → sample."""
    override = os.environ.get(CONFIG_PATH_ENV, "").strip()
    if override:
        return Path(override)
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    return CONFIG_SAMPLE_PATH


def _is_sample(src: Path) -> bool:
    """``src`` is the committed sample itself — by any spelling of its path."""
    try:
        return src.resolve() == CONFIG_SAMPLE_PATH.resolve()
    except OSError:
        return src == CONFIG_SAMPLE_PATH


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _as_float(value: Any, default: float, key: str) -> float:
    """A non-negative float from the file, or ``default`` with a warning.

    Same contract as :func:`_as_int` — absent takes the default silently,
    present-but-unusable earns a log line. A negative interval is unusable
    rather than "off": ``0`` is the documented way to turn a cadence off, and
    silently reading ``-1`` as that would hide a typo in the config.
    """
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        logger.warning("⚠️ config: invalid %s %r — falling back to %s", key, value, default)
        return default
    if out < 0:
        logger.warning("⚠️ config: %s cannot be negative (%r) — falling back to %s", key, value, default)
        return default
    return out


def _as_int(value: Any, default: int, key: str) -> int:
    """An int from the file, or ``default`` with a warning — never a crash.

    ``None`` (the key is absent) takes the default silently; a value that is
    there but unusable is worth a line in the log, the same way an invalid
    ``port`` is.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("⚠️ config: invalid %s %r — falling back to %d", key, value, default)
        return default


def _flatten_placeholders(raw: dict[str, Any]) -> dict[str, str]:
    """``{"onedrive": "E:/onedrive", "sharepoint": {"docs": "…"}}`` → flat tokens.

    A nested map becomes ``<group>:<name>`` keys (``sharepoint:docs``), which
    is exactly the token spelled inside a folder ref (``{sharepoint:docs}``),
    so :func:`resolve_placeholders` needs no special case. Scalars stay as
    they are.
    """
    flat: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                flat[f"{key}:{sub}"] = str(sub_value)
        else:
            flat[str(key)] = str(value)
    return flat


def load_config(path: Path | None = None) -> AppConfig:
    """Parse ``path`` (default: :func:`config_path`) into an :class:`AppConfig`.

    A missing or unparseable file logs a warning and yields the defaults —
    the webapp must still boot so the failure is visible in the UI/log rather
    than as a dead port.
    """
    src = path or config_path()
    raw: dict[str, Any] = {}
    try:
        raw = _as_dict(json.loads(src.read_text(encoding="utf-8")))
    except FileNotFoundError:
        logger.warning("⚠️ config: %s not found — using built-in defaults", src)
    except (OSError, ValueError) as exc:
        logger.warning("⚠️ config: could not parse %s (%s) — using built-in defaults", src, exc)

    issues = _as_dict(raw.get("issues"))
    mirror = _as_dict(raw.get("mirror"))
    if _is_sample(src):
        # The sample documents the shape; its placeholders resolve to a real
        # synced folder on the developer's machine. A checkout without its own
        # config/config.json (a fresh clone, a git worktree) must therefore
        # never mirror or back up into it: two databases rendering into one
        # folder is how the live one lost data (#126). Everything read-only
        # (search roots, the issue provider) keeps working from the sample.
        mirror = {"dir": "", "backup_dir": ""}
        logger.warning(
            "⚠️ config: no config/config.json — using the committed sample; the markdown mirror and "
            "the backup stay off until you create it (the sample is documentation, never a folder to write into)"
        )
    search = _as_dict(raw.get("search"))
    capture = _as_dict(raw.get("capture"))
    voice = _as_dict(raw.get("voice"))
    enrich = _as_dict(raw.get("enrich"))
    ai = _as_dict(raw.get("ai"))
    archive = _as_dict(raw.get("archive"))
    team = _as_dict(raw.get("team"))
    auth = _as_dict(raw.get("auth"))
    placeholders = _flatten_placeholders(_as_dict(raw.get("placeholders")))
    # same nested-map flattening as placeholders: web_roots.sharepoint.docs → "sharepoint:docs"
    web_roots = _flatten_placeholders(_as_dict(raw.get("web_roots")))

    try:
        port = int(raw.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        logger.warning("⚠️ config: invalid port %r — falling back to %d", raw.get("port"), DEFAULT_PORT)
        port = DEFAULT_PORT

    return AppConfig(
        site=str(raw.get("site", "home")),
        port=port,
        issues=IssuesConfig(
            provider=str(issues.get("provider", "github")),
            owner=str(issues.get("owner", "")),
            assignee=str(issues.get("assignee", "@me")),
            sync_minutes=int(issues.get("sync_minutes", 10) or 10),
        ),
        placeholders=placeholders,
        web_roots=web_roots,
        mirror=MirrorConfig(
            dir=str(mirror.get("dir", MirrorConfig.dir)),
            backup_dir=str(mirror.get("backup_dir", MirrorConfig.backup_dir)),
        ),
        search=SearchConfig(
            folder_roots=_as_str_list(search.get("folder_roots")),
            email_db=str(search.get("email_db", "")),
        ),
        capture=CaptureConfig(
            email_poll_minutes=_as_int(
                capture.get("email_poll_minutes"), CaptureConfig.email_poll_minutes,
                "capture.email_poll_minutes",
            ),
        ),
        voice=VoiceConfig(
            transcribe_url=str(voice.get("transcribe_url", VoiceConfig.transcribe_url) or "").strip(),
            fallback_url=str(voice.get("fallback_url", VoiceConfig.fallback_url) or "").strip(),
            partial_interval_seconds=_as_float(
                voice.get("partial_interval_seconds"), VoiceConfig.partial_interval_seconds,
                "voice.partial_interval_seconds",
            ),
        ),
        enrich=EnrichConfig(
            url=str(enrich.get("url", EnrichConfig.url) or "").strip(),
            model=str(enrich.get("model", EnrichConfig.model) or "").strip(),
            timeout_seconds=_as_float(
                enrich.get("timeout_seconds"), EnrichConfig.timeout_seconds,
                "enrich.timeout_seconds",
            ),
        ),
        ai=AIConfig(
            enabled=bool(ai.get("enabled", AIConfig.enabled)),
            base_url=str(ai.get("base_url", AIConfig.base_url) or "").strip(),
            model=str(ai.get("model", AIConfig.model) or "").strip(),
            timeout_seconds=_as_float(
                ai.get("timeout_seconds"), AIConfig.timeout_seconds,
                "ai.timeout_seconds",
            ),
        ),
        archive=ArchiveConfig(
            enabled=bool(archive.get("enabled", ArchiveConfig.enabled)),
            repo=str(archive.get("repo", "") or "").strip(),
            python=str(archive.get("python", "") or "").strip(),
            candidates=_as_int(
                archive.get("candidates"), ArchiveConfig.candidates, "archive.candidates",
            ),
            confidence_threshold=_as_float(
                archive.get("confidence_threshold"), ArchiveConfig.confidence_threshold,
                "archive.confidence_threshold",
            ),
            timeout_seconds=_as_float(
                archive.get("timeout_seconds"), ArchiveConfig.timeout_seconds,
                "archive.timeout_seconds",
            ),
            model=str(archive.get("model", ArchiveConfig.model) or "").strip(),
            batch_size=_as_int(
                archive.get("batch_size"), ArchiveConfig.batch_size, "archive.batch_size",
            ),
            examples=_as_int(
                archive.get("examples"), ArchiveConfig.examples, "archive.examples",
            ),
            ai_timeout_seconds=_as_float(
                archive.get("ai_timeout_seconds"), ArchiveConfig.ai_timeout_seconds,
                "archive.ai_timeout_seconds",
            ),
            renumber=bool(archive.get("renumber", ArchiveConfig.renumber)),
        ),
        team=TeamConfig(
            enabled=bool(team.get("enabled", False)),
            people=_as_str_list(team.get("people")),
        ),
        auth=AuthConfig(
            token=str(auth.get("token", "") or "").strip(),
            password_hash=str(auth.get("password_hash", "") or "").strip(),
        ),
        source_path=src,
    )


def save_auth(*, token: str | None = None, password_hash: str | None = None, path: Path | None = None) -> Path:
    """Write ``auth.token`` / ``auth.password_hash`` into the **real** config.

    Only the fields passed (non-``None``) change; everything else in the file
    is preserved. A missing ``config/config.json`` is created from the
    committed sample first — the sample itself is never written (it is the
    public twin and must keep both fields empty). Used by ``scripts/gen_token.py``
    and ``scripts/set_password.py``; the running app re-reads config on
    restart only (``tray.bat --restart``).
    """
    target = path or CONFIG_PATH
    if target == CONFIG_SAMPLE_PATH:
        raise ValueError("refusing to write secrets into config.sample.json")
    if target.exists():
        raw = _as_dict(json.loads(target.read_text(encoding="utf-8")))
    else:
        raw = _as_dict(json.loads(CONFIG_SAMPLE_PATH.read_text(encoding="utf-8")))
        logger.info("ℹ️ config: creating %s from the sample", target)
    auth = _as_dict(raw.get("auth"))
    if token is not None:
        auth["token"] = token
    if password_hash is not None:
        auth["password_hash"] = password_hash
    raw["auth"] = {"token": str(auth.get("token", "")), "password_hash": str(auth.get("password_hash", ""))}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
