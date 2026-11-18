"""The folder of the front File Explorer window, asked of folder-explorer.

Reading a Windows shell window is folder-explorer's job (``src/explorer_window.py``
there); this module only asks its v1 route ``GET /api/v1/explorer/folder`` and
turns every way the answer can fail into one :class:`ExplorerWindowError` whose
``code`` names the condition, so the Folder field never reads "no window open"
as "folder-explorer is down" or fills itself from a guess:

- ``folders_unavailable``       this install names no folder-explorer address;
- ``folder_explorer_unreachable``  no answer at all, or none in time;
- ``folder_explorer_outdated``  it answered, but has no such route (a build from before it existed);
- ``no_explorer_window``        no File Explorer folder window is open;
- ``explorer_unavailable``      Windows could not say which folders are open;
- ``not_this_pc``               folder-explorer was asked from a machine that is not its own.

``docs/service-api.md`` in folder-explorer is the contract.
"""

from __future__ import annotations

import logging

import requests

from src.search.folder_explorer import SCHEMA_VERSION, FolderExplorerClient

logger = logging.getLogger(__name__)

__all__ = ["ExplorerWindowError", "front_explorer_folder"]

_PATH = "/api/v1/explorer/folder"
#: Reading the shell's windows is quick; a stuck one must not hold the Folder field for long.
TIMEOUT_S = 5.0

_STATUS = {
    "folders_unavailable": 503,
    "folder_explorer_unreachable": 502,
    "folder_explorer_outdated": 502,
    "no_explorer_window": 404,
    "explorer_unavailable": 502,
    "not_this_pc": 403,
}


class ExplorerWindowError(Exception):
    """A read that could not give a folder: ``code`` names why, the message says it in words."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = _STATUS.get(code, 502)


def front_explorer_folder(client: FolderExplorerClient | None) -> str:
    """The absolute path of the foremost File Explorer folder window, or :class:`ExplorerWindowError`."""
    if client is None or not client.configured:
        raise ExplorerWindowError(
            "folders_unavailable", "No folder-explorer is set up here (search.folder_explorer_url), so the Explorer window can't be read",
        )
    try:
        resp = client.get(_PATH, TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("⚠️ explorer window: folder-explorer did not answer (%s)", type(exc).__name__)
        raise ExplorerWindowError(
            "folder_explorer_unreachable", f"folder-explorer at {client.host} did not answer ({type(exc).__name__})",
        ) from exc
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or "state" not in body:
        logger.warning("⚠️ explorer window: HTTP %s without a v1 envelope", resp.status_code)
        if resp.status_code == 404:
            raise ExplorerWindowError(
                "folder_explorer_outdated", "This folder-explorer can't report the Explorer window yet: update it and try again",
            )
        raise ExplorerWindowError(
            "folder_explorer_outdated", f"folder-explorer answered HTTP {resp.status_code} without a v1 envelope",
        )
    if body.get("schema_version") != SCHEMA_VERSION:
        raise ExplorerWindowError(
            "folder_explorer_outdated",
            f"folder-explorer speaks schema_version {body.get('schema_version')!r}, not {SCHEMA_VERSION}",
        )
    if body.get("state") == "ok":
        path = body.get("folder_path")
        if isinstance(path, str) and path.strip():
            return path
        raise ExplorerWindowError("explorer_unavailable", "folder-explorer said ok but named no folder")
    code = str(body.get("code") or "")
    reason = str(body.get("reason") or "")
    if code == "no_explorer_folder":
        raise ExplorerWindowError(
            "no_explorer_window", reason or "No File Explorer folder is open: open the folder in File Explorer and try again",
        )
    if code == "not_this_pc":
        raise ExplorerWindowError("not_this_pc", reason or "folder-explorer reads windows for its own PC only")
    raise ExplorerWindowError(
        "explorer_unavailable", reason or f"folder-explorer could not read the Explorer window ({code or 'error'})",
    )
