"""Folder index — the searchable list of folders under ``config.search.folder_roots``.

Wraps the vendored ``src/vendor/foldersearcher_core.py`` (the GUI-free half of
the fleet's folder searcher — scan, sectioned index file, substring AND
search) with what task-os needs around it:

- **placeholder-aware roots** — ``["{onedrive}/Documentos"]`` resolves through
  ``config.placeholders`` (:mod:`src.placeholders`); a root that does not
  resolve, or does not exist, is reported, never silently skipped;
- **one index file**, ``data/folder_index.txt`` (next to the database, so a
  disposable instance with ``TASKOS_DB_PATH`` in a temp dir indexes into that
  temp dir);
- :meth:`FolderIndexService.reindex` — the job: run at startup when the file
  is missing or older than :data:`STALE_AFTER` (in a daemon thread, so a
  large tree never delays the port), on ``POST /api/folders/reindex`` and on
  ``tasks folders reindex`` (foreground);
- :meth:`FolderIndexService.search` → ``[{path, ref, name, depth}]`` where
  ``ref`` is the path folded back onto the placeholders (:func:`to_ref`), so
  attaching a hit to a task stores a portable ref, never this PC's path;
- :meth:`FolderIndexService.status` for ``/api/status`` — ``configured``,
  ``roots`` (each with its resolved path and whether it exists), ``entries``,
  ``last_indexed``, ``indexing`` and the ``reason`` when off.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.db import db_path
from src.placeholders import normalize_path, resolve, to_ref
from src.vendor import foldersearcher_core as core

logger = logging.getLogger(__name__)

INDEX_FILE_NAME = "folder_index.txt"
STALE_AFTER_S = 24 * 3600
_RECHECK_S = 3600
DEFAULT_LIMIT = 30


def default_index_path() -> Path:
    return db_path().parent / INDEX_FILE_NAME


class FolderIndexService:
    """Roots + index file + the in-memory :class:`core.FolderIndex`, thread-safe."""

    def __init__(self, config: AppConfig, *, index_path: Path | None = None) -> None:
        self.placeholders = dict(config.placeholders)
        self.index_path = index_path or default_index_path()
        self.roots: list[dict[str, Any]] = []
        self.reason = ""
        for raw in config.search.folder_roots:
            r = resolve(raw, self.placeholders)
            entry: dict[str, Any] = {"ref": raw, "path": r.path if r.resolved else None, "exists": False}
            if not r.resolved:
                entry["error"] = "unresolved placeholder(s) " + ", ".join("{" + m + "}" for m in r.unresolved)
            else:
                entry["exists"] = os.path.isdir(r.path)
                if not entry["exists"]:
                    entry["error"] = "folder not found on this PC"
            self.roots.append(entry)
        if not self.roots:
            self.reason = "search.folder_roots not configured"
        elif not any(r["exists"] for r in self.roots):
            self.reason = "no folder root usable on this PC — " + "; ".join(f"{r['ref']}: {r.get('error')}" for r in self.roots)
        self._index = core.FolderIndex()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.indexing = False
        self.last_indexed: str | None = None
        self.last_error: str | None = None
        self.last_duration_s: float | None = None
        if self.reason:
            logger.warning("⚠️ folder index disabled — %s", self.reason)

    # ---------------------------------------------------------------- state

    @property
    def enabled(self) -> bool:
        return not self.reason

    @property
    def scan_roots(self) -> list[str]:
        return [str(r["path"]) for r in self.roots if r.get("path")]

    def _file_age_s(self) -> float | None:
        try:
            return time.time() - self.index_path.stat().st_mtime
        except OSError:
            return None

    def _stamp_from_file(self) -> None:
        try:
            self.last_indexed = datetime.fromtimestamp(self.index_path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        except OSError:
            self.last_indexed = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            entries = len(self._index)
        return {
            "enabled": self.enabled,
            "configured": bool(self.roots),
            "reason": self.reason or None,
            "roots": [dict(r) for r in self.roots],
            "index_file": str(self.index_path),
            "entries": entries,
            "last_indexed": self.last_indexed,
            "indexing": self.indexing,
            "last_error": self.last_error,
            "last_duration_s": self.last_duration_s,
            "stale": (self._file_age_s() or 0) > STALE_AFTER_S if self.last_indexed else True,
        }

    # -------------------------------------------------------------- actions

    def load(self) -> int:
        """Read the index file into memory (no scan). Returns the entry count."""
        fresh = core.FolderIndex()
        n = fresh.load(str(self.index_path))
        with self._lock:
            self._index = fresh
        self._stamp_from_file()
        return n

    def reindex(self) -> dict[str, Any]:
        """Scan every resolvable root, write the index file, swap it in. Foreground."""
        if not self.enabled:
            raise RuntimeError(self.reason)
        self.indexing = True
        started = time.monotonic()
        try:
            fresh = core.FolderIndex()
            n = fresh.scan(self.scan_roots)
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            fresh.save(str(self.index_path))
            with self._lock:
                self._index = fresh
            self.last_error = None
            self._stamp_from_file()
            self.last_duration_s = round(time.monotonic() - started, 2)
            logger.info("✅ folder index: %d folder(s) across %d root(s) in %.1fs → %s",
                        n, len(self.scan_roots), self.last_duration_s, self.index_path)
            for r in self.roots:
                if r.get("path"):
                    r["exists"] = os.path.isdir(str(r["path"]))
            return {"entries": n, "roots": self.scan_roots, "seconds": self.last_duration_s, "index_file": str(self.index_path)}
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("❌ folder index: reindex failed")
            raise
        finally:
            self.indexing = False

    def search(self, q: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """Substring AND search over every indexed path → ``[{path, ref, name, depth}]``."""
        with self._lock:
            index = self._index
        hits = core.search(index, q, skip_depth=0)
        out: list[dict[str, Any]] = []
        for hit in hits[: max(0, int(limit))]:
            path = normalize_path(hit.absolute_path)
            out.append({
                "path": path,
                "ref": to_ref(path, self.placeholders),
                "name": path.rstrip("/").rsplit("/", 1)[-1] or path,
                "depth": self._depth(path),
            })
        return out

    def _depth(self, path: str) -> int:
        low = path.lower()
        for root in self.scan_roots:
            r = root.rstrip("/").lower()
            if low == r:
                return 0
            if low.startswith(r + "/"):
                return path[len(r) + 1:].count("/") + 1
        return path.count("/")

    # ----------------------------------------------------------- background

    def start(self) -> None:
        """Load the file if fresh, else reindex — in a daemon thread; then re-check hourly."""
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="task-os-folder-index", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _tick(self) -> None:
        age = self._file_age_s()
        if age is not None and age <= STALE_AFTER_S:
            if not len(self._index):
                n = self.load()
                logger.info("ℹ️ folder index: loaded %d folder(s) from %s (%.0f h old)", n, self.index_path, age / 3600)
            return
        why = "missing" if age is None else f"{age / 3600:.0f} h old"
        logger.info("ℹ️ folder index: %s — reindexing %s", why, ", ".join(self.scan_roots))
        try:
            self.reindex()
        except Exception:  # noqa: BLE001 — logged inside; the loop keeps going
            pass

    def _run(self) -> None:
        self._tick()
        while not self._stop.wait(_RECHECK_S):
            self._tick()
