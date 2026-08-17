"""FastAPI webapp — the task-os PWA server.

Route families (each in ``app/webapp/routers/``):

    misc    GET /                → PWA shell (hash-stamped, no-cache)
            GET /static/{path}   → CSS / JS / icons (CachingStaticFiles mount)
            GET /healthz         → liveness
            GET /api/version     → build identity (git_sha, asset_hash, schema_version)
    tasks   /api/tasks…          → CRUD, tree, move, done, comments, links, issue; /api/activity
    people  /api/people…         → contacts / assignees CRUD
    search  /api/search?q=       → full text over tasks + comments
    views   /api/board · /api/today → the Board's five buckets · Today grouped by project
    mirror  /api/status          → install status: https + auth (Step 7), markdown mirror +
                                   backup; POST /api/mirror/export, /api/mirror/import,
                                   /api/backup run them on demand
    auth    GET /login · POST /api/login|logout — the token / password →
            cookie swap (Step 7)

Access (``src.auth.AuthMiddleware``): loopback is the owner; any other client
needs the bearer token (header or the ``taskos_token`` cookie ``/login``
sets). Static assets, ``/healthz``, ``/api/version`` and ``/login`` stay
public. HTTPS is uvicorn's job (``--ssl-*`` from ``app.webapp.manager`` /
``webapp.bat`` when ``webapp/certificates/{cert,key}.pem`` exist).

Background services (started in the lifespan, stopped on shutdown, exposed
on ``app.state``): ``src.mirror.Mirror`` (debounced export on every write via
the repo's write listener + the 2 s import watcher) and
``src.backup.BackupScheduler`` (daily 03:00 copy + a startup copy when
today's is missing). Both stay disabled — with a logged, ``/api/status``-
visible reason — when their folder is not configured.

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

from app.webapp.routers import auth, mirror, misc, people, search, tasks, views
from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR, error_response
from src.auth import AuthMiddleware
from src.backup import BackupScheduler
from src.certs import cert_paths
from src.config import load_config
from src.db import db_path, init_db
from src.logger import configure_logging
from src.mirror import Mirror
from src.tasks_repo import RepoError

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
    app.state.mirror.start()
    app.state.backup.start()
    try:
        yield
    finally:
        app.state.mirror.stop()
        app.state.backup.stop()


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
    return app


# Module-level app for ``uvicorn app.webapp.server:app``.
app = create_app()
