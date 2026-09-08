"""FastAPI webapp — the task-os PWA server.

Route families (each in ``app/webapp/routers/``):

    misc    GET /                → PWA shell (hash-stamped, no-cache)
            GET /static/{path}   → CSS / JS / icons (CachingStaticFiles mount)
            GET /healthz         → liveness
            GET /api/version     → build identity (git_sha, asset_hash, schema_version)
    tasks   /api/tasks…          → CRUD, tree, move, done, comments, links, issue; /api/activity
    people  /api/people…         → contacts / assignees CRUD
    search  /api/search?q=&kinds=&limit= → federated: tasks · folders · emails · issues,
                                   grouped, unconfigured = visible; /api/search/status
    views   /api/board · /api/today → the Board's five buckets · Today grouped by project
    mirror  /api/status          → install status: https + auth (Step 7), markdown mirror +
                                   backup, folder index + opener (Step 9), capture (#98),
                                   local AI (#95); POST
                                   /api/mirror/export, /api/mirror/import, /api/backup
                                   run them on demand
    folders POST /api/resolve    → folder ref ↔ absolute path (placeholders, Step 9)
            /api/folders/search  → the folder index; POST /api/folders/reindex
            /opener/opener.cmd   → the per-PC handler a second PC downloads (public)
    issues  /api/issues/status · POST /api/issues/sync · GET/POST /api/tasks/{id}/issue
                                 → the issue provider (GitHub via gh): status, sync now,
                                   the drawer's issue panel, create an issue from a task
    capture POST /api/capture/email/run → one flagged-email pass now (#98); the
                                   poller's own state rides /api/status's `capture`
    voice   POST /api/transcribe  → the recorded clip forwarded to the fleet's
                                   whisper server, back as {text, parse} (#92); the
                                   endpoint's own state rides /api/status's `voice`
    ai      GET /api/ai/suggestions · POST /api/ai/triage and individual
                                   accept/reject → staged Inbox proposals (#95)
    auth    GET /login · POST /api/login|logout — the token / password →
            cookie swap (Step 7)

Access (``src.auth.AuthMiddleware``): loopback is the owner; any other client
needs the bearer token (header or the ``taskos_token`` cookie ``/login``
sets). Static assets, ``/healthz``, ``/api/version`` and ``/login`` stay
public. HTTPS is uvicorn's job (``--ssl-*`` from ``app.webapp.manager`` /
``webapp.bat`` when ``webapp/certificates/{cert,key}.pem`` exist).

Background services (started in the lifespan, stopped on shutdown, exposed
on ``app.state``): ``src.mirror.Mirror`` (debounced export on every write via
the repo's write listener + the 2 s import watcher),
``src.backup.BackupScheduler`` (daily 03:00 copy + a startup copy when
today's is missing), ``src.issue_sync.IssueSyncService`` (the forge's
open issues → coding tasks, first pass 10 s after startup then every
``issues.sync_minutes``), ``src.folder_index.FolderIndexService`` (startup
reindex when the index file is missing / older than 24 h, hourly re-check) and
``src.email_capture.EmailCaptureService`` (flagged emails in the archiver's
read-only index → Inbox tasks, every ``capture.email_poll_minutes``).
``src.voice.VoiceClient`` (``app.state.voice``), ``src.enrich.EnrichClient``
(``app.state.enrich``, #147) and ``src.ai.AIClient`` (``app.state.ai``, #95)
are the exceptions with no
thread to start: voice quick-add (#92) is a cached reachability probe of the
transcription endpoint plus one forwarding POST per recording, and enrichment
is the same shape against the hub's chat endpoint. AI triage makes one bounded
Anthropic-shape request and stages its validated answer for explicit review.
All stay disabled — with a logged, status-visible reason — when not
configured. ``src.search.FederatedSearch`` (``app.state.search``) is built
over the folder-index and issue-sync services so the search box reads the same
folder index and issue cache they keep warm. The lifespan also installs the repo's folder
resolvers (``src.placeholders``: path + ``config.web_roots`` cloud twin, #28)
so every task payload carries ``folder_resolved`` / ``folder_url``.

Errors are one JSON envelope everywhere — ``{"error": {"code", "message",
"detail"?}}`` — for domain errors (``src.tasks_repo.RepoError`` → its
``http_status``), request-validation failures (422) and plain HTTP errors.

Run under uvicorn with the pinned selector loop (Windows proactor wedges on an
aborted client — app-launcher#388):

    python -m uvicorn app.webapp.server:app --host 0.0.0.0 --port 8448 \
        --loop app.webapp.event_loop:selector_loop_factory
"""

from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.webapp.routers import (
    ai,
    auth,
    capture,
    folders,
    issues,
    mirror,
    misc,
    people,
    search,
    tasks,
    views,
    voice,
)
from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR, error_response
from src import placeholders
from src import tasks_repo as repo
from src.ai import AIClient
from src.auth import AuthMiddleware
from src.backup import BackupScheduler
from src.certs import cert_paths
from src.config import load_config
from src.db import db_path, init_db
from src.email_capture import EmailCaptureService
from src.enrich import EnrichClient
from src.folder_index import FolderIndexService
from src.issue_sync import IssueSyncService
from src.logger import configure_logging
from src.mirror import Mirror
from src.search import build_federated
from src.tasks_repo import RepoError
from src.voice import VoiceClient

logger = logging.getLogger(__name__)

# Hash-stamped assets cache for a year (the fleet hash in the URL is the cache
# key, so a stale copy can never be served); icons + manifest revalidate
# daily; the shell itself is served no-cache by the index route.
_LONG_CACHE = "public, max-age=31536000, immutable"
_DAY_CACHE = "public, max-age=86400"
_IMMUTABLE_SUFFIXES = frozenset({".js", ".css"})
_DAILY_SUFFIXES = frozenset({".webmanifest", ".png", ".ico", ".svg"})


class CachingStaticFiles(StaticFiles):
    """``StaticFiles`` with per-suffix ``Cache-Control`` + JS-import stamping.

    Starlette's mount sends only ``ETag`` / ``Last-Modified``, which lets an
    installed iOS PWA heuristic-cache the module graph across deploys. This
    subclass stamps an explicit policy per suffix and rewrites each served
    ``.js`` module's relative ``import`` URLs with the build's fleet hash so an
    edit to any module busts the whole graph (project-scaffolding#78).
    """

    def file_response(
        self,
        full_path: os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        path = Path(full_path)
        suffix = path.suffix.lower()

        if suffix == ".js":
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                return super().file_response(full_path, stat_result, scope, status_code)
            media_type, _ = mimetypes.guess_type(str(path))
            return Response(
                content=BUILD_INFO.stamp_js(body, path),
                status_code=status_code,
                media_type=media_type or "text/javascript",
                headers={"Cache-Control": _LONG_CACHE},
            )

        response = super().file_response(full_path, stat_result, scope, status_code)
        if suffix in _IMMUTABLE_SUFFIXES:
            response.headers["Cache-Control"] = _LONG_CACHE
        elif suffix in _DAILY_SUFFIXES:
            response.headers["Cache-Control"] = _DAY_CACHE
        return response


def _folder_resolver_for(ph: dict[str, str]):
    """``ref → absolute path`` for the repo's summaries; ``None`` (unknown) when
    a placeholder is missing from this install's config — never a half path."""
    def _resolve(ref: str) -> str | None:
        r = placeholders.resolve(ref, ph)
        return r.path if r.resolved else None
    return _resolve


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    version = init_db()
    logger.info(
        "✅ task-os webapp up — build %s · assets %s · db %s (schema v%d)",
        BUILD_INFO.git_sha,
        BUILD_INFO.fleet_hash or "missing",
        db_path(),
        version,
    )
    # Access + transport, said once and loudly: an unestablished fact is its
    # own visible state, never folded into "fine".
    if app.state.config.auth.enabled:
        logger.info("🔐 auth: token configured — non-loopback clients sign in at /login")
    else:
        logger.warning("⚠️ auth: no token in config — only this PC (loopback) can use the app; run scripts/gen_token.py")
    if cert_paths() is None:
        logger.warning("⚠️ https: no webapp/certificates/{cert,key}.pem — the launcher serves plain HTTP; run scripts/gen_tailscale_cert.py")
    config = app.state.config
    app.state.mirror = Mirror(config)
    app.state.backup = BackupScheduler(config)
    app.state.issues = IssueSyncService(config)
    app.state.folders = FolderIndexService(config)
    app.state.capture = EmailCaptureService(config)
    # No thread and nothing to start: the voice client is a cached reachability
    # probe plus one forwarding POST (#92).
    app.state.voice = VoiceClient(config)
    # Same shape, same reason (#147): a cached probe plus one POST per
    # spoken line. Enrichment is a tidy-up on an answer that already
    # exists, so it never has anything to keep running.
    app.state.enrich = EnrichClient(config)
    # One Anthropic-SDK client for staged triage now and generated notes later.
    # No worker of its own: a cached reachability probe plus explicit requests.
    app.state.ai = AIClient(config)
    app.state.search = build_federated(config, folders=app.state.folders, issues=app.state.issues)
    for a in app.state.search.status():
        if not a["configured"]:
            logger.warning("⚠️ search: %s adapter off — %s", a["kind"], a["reason"])
    repo.set_folder_resolver(_folder_resolver_for(config.placeholders))
    repo.set_folder_web_resolver(lambda ref: placeholders.web_url(ref, config.web_roots))
    app.state.mirror.start()
    app.state.backup.start()
    app.state.issues.start()
    app.state.folders.start()
    app.state.capture.start()
    try:
        yield
    finally:
        app.state.mirror.stop()
        app.state.backup.stop()
        app.state.issues.stop()
        app.state.folders.stop()
        app.state.capture.stop()
        repo.set_folder_resolver(None)
        repo.set_folder_web_resolver(None)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RepoError)
    async def _repo_error(request: Request, exc: RepoError) -> Response:
        return error_response(exc.http_status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        return error_response(422, "validation_error", "invalid request", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, code, str(exc.detail))


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="task-os", version="0.2.0", lifespan=_lifespan)
    app.state.config = load_config()
    app.state.build_info = BUILD_INFO
    _install_error_handlers(app)
    app.add_middleware(AuthMiddleware, get_auth=lambda: app.state.config.auth)
    if STATIC_DIR.exists():
        app.mount("/static", CachingStaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(misc.router)
    app.include_router(auth.router)
    app.include_router(tasks.router)
    app.include_router(people.router)
    app.include_router(search.router)
    app.include_router(views.router)
    app.include_router(mirror.router)
    app.include_router(issues.router)
    app.include_router(folders.router)
    app.include_router(capture.router)
    app.include_router(voice.router)
    app.include_router(ai.router)
    return app


# Module-level app for ``uvicorn app.webapp.server:app``.
app = create_app()
