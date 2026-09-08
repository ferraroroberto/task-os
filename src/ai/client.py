"""One bounded Anthropic-SDK client for task-os AI features (#95).

The endpoint is local-llm-hub, never a provider URL or an inline CLI process.
Configuration decides whether AI is enabled and which live hub model alias to
use. A reachability probe is deliberately separate from generation: status can
say *disabled* versus *hub unavailable*, while a real request remains the only
proof that a model produced usable text.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any

import anthropic

from src import clock
from src.config import AppConfig
from src.voice import endpoint_of

logger = logging.getLogger(__name__)

PROBE_TTL_SECONDS = 15.0
PROBE_TIMEOUT_SECONDS = 1.5


class AIError(RuntimeError):
    """A classified AI failure safe to turn into the standard API envelope."""

    def __init__(self, code: str, message: str, *, http_status: int, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.detail = detail


class AIClient:
    """Configured local-hub client with cached status and one-shot generation.

    ``model`` and ``timeout`` override ``ai.model`` / ``ai.timeout_seconds`` for
    a feature that needs its own (archive ranking, #158, uses ``archive.model``
    and ``archive.ai_timeout_seconds``: a batch of mails is a far longer request
    than one triage, because an open-weight model emits its reasoning before the
    answer). Each instance carries its own in-flight lock, so two features never
    serialise each other on the hub; the endpoint and the enabled switch stay
    one setting for the whole app.
    """

    def __init__(
        self, config: AppConfig, *, model: str | None = None, timeout: float | None = None,
    ) -> None:
        self.configured_enabled = bool(config.ai.enabled)
        self.base_url = (config.ai.base_url or "").strip().rstrip("/")
        self.model = ((model if model else config.ai.model) or "").strip()
        self.timeout = float(timeout if timeout else config.ai.timeout_seconds)
        self._lock = threading.Lock()
        self._verdict: tuple[float, bool, str | None] | None = None
        self._checked_at: str | None = None
        self._client: anthropic.Anthropic | None = None
        self._request_lock = threading.Lock()

    @property
    def unconfigured_reason(self) -> str | None:
        """Stable public reason when configuration itself prevents AI use."""
        if not self.configured_enabled:
            return "disabled in config"
        if not self.base_url:
            return "no ai.base_url in config"
        if endpoint_of(self.base_url) is None:
            return "ai.base_url is not a valid HTTP address"
        if not self.model:
            return "no ai.model in config"
        return None

    def probe(self, *, force: bool = False) -> tuple[bool, str | None]:
        """Return ``(reachable, public_reason)`` without sending task content."""
        reason = self.unconfigured_reason
        if reason:
            return False, reason
        with self._lock:
            cached = self._verdict
            if cached and not force and time.monotonic() < cached[0]:
                return cached[1], cached[2]
        endpoint = endpoint_of(self.base_url)
        assert endpoint is not None
        host, port = endpoint
        detail: str | None = None
        try:
            with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS):
                pass
        except OSError as exc:
            detail = f"{exc.__class__.__name__}: {exc}"
        public_reason = None if detail is None else "local AI hub unavailable"
        with self._lock:
            self._verdict = (
                time.monotonic() + PROBE_TTL_SECONDS,
                detail is None,
                public_reason,
            )
            self._checked_at = clock.now_iso()
        if detail:
            logger.info("ℹ️ ai: reachability check failed — %s", detail)
        return detail is None, public_reason

    def status(self) -> dict[str, Any]:
        """Status shape used by the Board, Settings, CLI and ``/api/status``."""
        reachable, reason = self.probe()
        return {
            "enabled": self.configured_enabled and reachable,
            "configured": self.configured_enabled and self.unconfigured_reason is None,
            "reachable": reachable,
            "reason": reason,
            "model": self.model or None,
            "checked_at": self._checked_at,
        }

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Make one non-streaming request; refuse concurrent AI work."""
        if not self._request_lock.acquire(blocking=False):
            raise AIError(
                "ai_in_flight", "another local AI request is already in progress", http_status=409,
            )
        try:
            return self._complete_once(system=system, user=user, max_tokens=max_tokens)
        finally:
            self._request_lock.release()

    def _complete_once(self, *, system: str, user: str, max_tokens: int) -> str:
        """The single SDK call behind :meth:`complete`."""
        reason = self.unconfigured_reason
        if reason:
            raise AIError("ai_disabled", reason, http_status=409)
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key="local-dummy",
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        started = time.monotonic()
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APITimeoutError as exc:
            logger.warning("⚠️ ai: hub request timed out after %.1f s", time.monotonic() - started)
            raise AIError(
                "ai_timeout", "local AI hub did not finish in time", http_status=504,
                detail=exc.__class__.__name__,
            ) from exc
        except anthropic.APIConnectionError as exc:
            with self._lock:
                self._verdict = None
            logger.warning("⚠️ ai: hub connection failed — %s", exc)
            raise AIError(
                "ai_unavailable", "local AI hub unavailable", http_status=503,
                detail=exc.__class__.__name__,
            ) from exc
        except anthropic.APIStatusError as exc:
            logger.warning("⚠️ ai: hub refused the request — HTTP %d", exc.status_code)
            raise AIError(
                "ai_refused", "local AI hub refused the request", http_status=502,
                detail=f"HTTP {exc.status_code}",
            ) from exc
        except anthropic.AnthropicError as exc:
            logger.warning("⚠️ ai: hub request failed — %s", exc)
            raise AIError(
                "ai_failed", "local AI request failed", http_status=502,
                detail=exc.__class__.__name__,
            ) from exc

        text = "\n".join(
            str(block.text) for block in message.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
        ).strip()
        elapsed = time.monotonic() - started
        logger.info(
            "ℹ️ ai: %d input chars → %d output chars in %.1f s via %s",
            len(user), len(text), elapsed, getattr(message, "model", None) or self.model,
        )
        if not text:
            raise AIError(
                "ai_empty_response", "local AI returned no suggestions", http_status=502,
                detail=f"stop_reason={getattr(message, 'stop_reason', None)}",
            )
        return text
