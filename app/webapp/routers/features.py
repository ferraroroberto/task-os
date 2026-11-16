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
          routes answer 409 ``feature_off``. No restart. 409 ``config_readonly`` when
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
from src.features import feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["features"])


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
    off = config.features_off - {key} if body.enabled else config.features_off | {key}
    # The file first: a switch the config cannot hold is never half-applied.
    try:
        save_features(off, path=config.source_path)
    except OSError as exc:
        logger.warning("⚠️ could not save features to %s: %s", config.source_path.name, exc)
        return error_response(500, "config_write_failed", "the config file could not be written")
    request.app.state.config = replace(config, features_off=off)
    apply_features(request.app)
    logger.info("ℹ️ features: %s switched %s", key, "on" if body.enabled else "off")
    return {"features": feature_rows(request.app)}
