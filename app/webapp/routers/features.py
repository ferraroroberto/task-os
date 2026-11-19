"""Available features — which coarse blocks of the app this machine runs.

    GET /api/features
        → {"features": [{key, label, summary, enabled, available, reason}, …]}
          every block in the order of ``src/features.py``; ``available: false`` + a
          ``reason`` when its dependency is missing on this machine (the switch still
          works, the block just has nothing to run on).
    PUT /api/features/{key}   {"enabled": bool}
        → the same list. Writes the machine-local ``features`` block of the config
          file the app loaded and applies it live: the block's UI hides (the page
          reads ``data-features-off``), its background services start or stop and its
          routes answer 409 ``feature_off``. No restart. The one opt-in block
          (``publish_address``, off by default) is written as ``true`` and publishes once
          when it is switched on; its row also carries ``detail`` (the last outcome). 409 ``config_readonly`` when
          the app runs on the committed sample, which is never written.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.webapp.features import apply_features, feature_rows
from app.webapp.routers._helpers import error_response
from src.config import can_write_config, save_features
from src.features import PUBLISH_ADDRESS, feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["features"])

#: How long switching the publish block on waits for its first attempt before answering.
_PUBLISH_WAIT_SECONDS = 2.0


class FeatureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/features")
def list_features(request: Request) -> dict[str, Any]:
    return {"features": feature_rows(request.app)}


@router.put("/features/{key}")
def set_feature(key: str, body: FeatureBody, request: Request) -> Any:
    if feature(key) is None:
        return error_response(404, "not_found", f"no feature block named {key!r}")
    config = request.app.state.config
    if not can_write_config(config.source_path):
        return error_response(
            409, "config_readonly",
            "this install is running without its own config file, so there is nowhere to save the switch",
        )
    block = feature(key)
    off, on = config.features_off, config.features_on
    if block is not None and block.default_on:
        off = off - {key} if body.enabled else off | {key}
    else:
        on = on | {key} if body.enabled else on - {key}
    # The file first: a switch the config cannot hold is never half-applied.
    try:
        save_features(off, on=on, path=config.source_path)
    except OSError as exc:
        logger.warning("⚠️ could not save features to %s: %s", config.source_path.name, exc)
        return error_response(500, "config_write_failed", "the config file could not be written")
    request.app.state.config = replace(config, features_off=off, features_on=on)
    apply_features(request.app)
    if key == PUBLISH_ADDRESS and body.enabled:
        # Enabling publishes once, at once; a slow share is given a moment, not the request.
        request.app.state.publisher.run(wait=_PUBLISH_WAIT_SECONDS)
    logger.info("ℹ️ features: %s switched %s", key, "on" if body.enabled else "off")
    return {"features": feature_rows(request.app)}
