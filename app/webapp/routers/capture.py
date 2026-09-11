"""Capture route family — the inbound channels that land tasks in Inbox (#98).

    POST /api/capture/email/run   one flagged-email pass now →
                                  {listed, created, unchanged, errors, created_ids}
                                  (409 + the reason when the poller is off)

There is deliberately no ``GET /api/capture/status`` twin: the poller's
enabled / reason / last_run / last_result / last_error ride ``GET /api/status``
under ``capture``, beside mirror, backup and folders, so the Settings pane and
``tasks status`` read the whole install in one call.

The other inbound channel needs no route of its own — whatsapp-radar posts to
``POST /api/tasks`` with an ``external_id`` and that route's own idempotency
(``tasks_repo.capture_task``) is the entire contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.webapp.routers._helpers import error_response, service_unavailable

router = APIRouter(prefix="/api", tags=["capture"])


@router.post("/capture/email/run")
def capture_email_run(request: Request) -> Any:
    service = getattr(request.app.state, "capture", None)
    if service is None or not service.enabled:
        return service_unavailable(service, "capture_disabled", "capture")
    result = service.run_now()
    if result is None:
        return error_response(500, "capture_failed", service.last_error or "capture pass failed")
    return result.to_dict()
