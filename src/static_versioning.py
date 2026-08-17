"""Build identity + static-asset versioning for the webapp.

Lets the mobile webapp prove which build it is running, so "did the
deploy take, or is the iPhone serving stale cached code?" stops being
answered by feel:

  * content-hash query stamps on every ``.js`` / ``.css`` asset so any
    edit changes the URL — no manual ``?v=N`` bumps, no stale iOS cache,
  * a build identity (git SHA + build time) surfaced via ``/api/version``
    and the glanceable ``Build:`` footer in the PWA.

The webapp is an ES-module graph (``index.html`` loads ``main.js`` which
imports the other modules). A naive per-file hash would go stale: if
``state.js`` changes but ``main.js`` does not, ``main.js``'s own bytes —
and so its hash — are unchanged, yet the module it pulls in is now
different. So we use a single **fleet hash** — one SHA-256 over the
concatenation of every hashable file's per-file hash. Any edit to any
asset rotates the fleet hash, so every ``?v=`` stamp changes and the
whole (tiny) module graph is re-fetched.

Every value is computed once when :class:`BuildInfo` is constructed at
webapp startup — the tray restarts on every code edit per project
convention, so there is no watcher and no per-request work.
"""

from __future__ import annotations

# Standard library imports
import hashlib
import logging
import posixpath
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable

# Local imports
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

_HASH_LEN = 8

# Suffixes under static/ that get hashed + ``?v=`` stamped. Everything
# else (icons, manifest) is cached conservatively by the static mount itself.
_HASHED_SUFFIXES = (".js", ".css")

# Subdirectories under static/ skipped entirely — third-party bundles
# (e.g. the vendored Chart.js UMD) carry their own version in the path
# and never benefit from a hash.
_SKIP_DIRS = ("vendor",)

# ``import ... from './foo.js'`` or ``'../dir/foo.js'`` — captures the
# whole quoted relative specifier (any number of ``./``/``../`` segments
# and subdirectories) so ``?v=<hash>`` can be stamped onto it. Any
# existing ``?v=…`` is captured too, so re-stamping an already-stamped
# body is idempotent.
_JS_IMPORT_RE = re.compile(
    r"""(from\s*['"])(\.\.?/(?:[\w\-.]+/)*[\w\-.]+\.js)(\?v=[^'"]*)?(['"])"""
)

# ``href`` / ``src`` pointing at a hashable ``/static/`` asset in
# index.html — including subdirectories (e.g. ``/static/_vendored/nav/
# nav-tabs.css``). Same idempotence rule as the JS import regex.
# ``/static/vendor/…`` paths still pass through unstamped because
# ``vendor`` never appears in the hash map (``_SKIP_DIRS``), not because
# the regex excludes them.
_INDEX_ASSET_RE = re.compile(
    r"""(href|src)=(['"])/static/([\w\-./]+\.(?:css|js))(\?v=[^'"]*)?(['"])"""
)


def _short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:_HASH_LEN]


def _iter_hashable_files(static_dir: Path) -> Iterable[Path]:
    for path in sorted(static_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(static_dir).parts[:-1]
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if path.suffix.lower() not in _HASHED_SUFFIXES:
            continue
        yield path


def compute_asset_hashes(static_dir: Path) -> Dict[str, str]:
    """Return ``{relpath: fleet_hash}`` for every hashable static file.

    Every value is the same fleet hash (see the module docstring); the
    dict is keyed by the file's static-dir-relative posix path (e.g.
    ``_vendored/nav/nav-tabs.css``), not the bare filename, so the
    rewriters can resolve subdirectory references and so two files
    sharing a basename in different directories don't collide. Falls
    back to an empty dict when the static dir or its files can't be
    read — a partial deploy then degrades to unstamped URLs rather than
    crashing the page.
    """
    if not static_dir.exists():
        return {}
    per_file: Dict[str, str] = {}
    for path in _iter_hashable_files(static_dir):
        try:
            relpath = path.relative_to(static_dir).as_posix()
            per_file[relpath] = _short_hash(path.read_bytes())
        except OSError as exc:
            logger.warning(f"⚠️  Could not hash {path} ({exc})")
    if not per_file:
        return {}
    fleet_input = "\n".join(
        f"{name}:{per_file[name]}" for name in sorted(per_file)
    ).encode("utf-8")
    fleet_hash = _short_hash(fleet_input)
    return {name: fleet_hash for name in per_file}


def fleet_hash_of(hashes: Dict[str, str]) -> str:
    """The single representative hash. Empty string if no assets."""
    if not hashes:
        return ""
    return next(iter(hashes.values()))


def rewrite_index_html(body: str, hashes: Dict[str, str]) -> str:
    """Stamp ``?v=<hash>`` onto every ``/static/<relpath>.(css|js)`` href/src.

    ``<relpath>`` may include subdirectories (e.g.
    ``_vendored/nav/nav-tabs.css``) since it maps directly onto a
    ``hashes`` key — no resolution needed, unlike a relative JS import.
    Unknown files pass through unchanged — robust against a new asset
    not yet in the hash map. Existing ``?v=…`` is replaced.
    """
    if not hashes:
        return body

    def _sub(match: "re.Match[str]") -> str:
        attr, quote_open, relpath, _existing, quote_close = match.group(
            1, 2, 3, 4, 5
        )
        stamp = hashes.get(relpath)
        if not stamp:
            return match.group(0)
        return f"{attr}={quote_open}/static/{relpath}?v={stamp}{quote_close}"

    return _INDEX_ASSET_RE.sub(_sub, body)


def _resolve_specifier(from_dir: str, spec: str) -> str:
    """Resolve a ``./``/``../`` import specifier against ``from_dir``.

    ``from_dir`` is the static-dir-relative posix directory of the file
    doing the importing (empty string at the static root). Returns the
    static-dir-relative posix path used as the ``hashes`` lookup key,
    e.g. ``_resolve_specifier("_vendored/empty-state", "../icons/icons.js")
    == "_vendored/icons/icons.js"``.
    """
    joined = posixpath.join(from_dir, spec) if from_dir else spec
    return posixpath.normpath(joined)


def rewrite_js_imports(body: str, hashes: Dict[str, str], from_dir: str = "") -> str:
    """Stamp ``?v=<hash>`` onto every relative ``import`` in ``body``.

    ``from_dir`` is the static-dir-relative posix directory of the file
    being rewritten (empty string for a file at the static root) —
    needed to resolve ``./`` and ``../`` specifiers (including into
    subdirectories, e.g. ``./_vendored/icons/icons.js``) against
    ``hashes``, which is keyed by static-dir-relative path. Imports with
    no matching entry are left alone. Existing ``?v=…`` is replaced, so
    re-rewriting a served body is idempotent.
    """
    if not hashes:
        return body

    def _sub(match: "re.Match[str]") -> str:
        prefix, spec, _existing, quote_close = match.group(1, 2, 3, 4)
        stamp = hashes.get(_resolve_specifier(from_dir, spec))
        if not stamp:
            return match.group(0)
        return f"{prefix}{spec}?v={stamp}{quote_close}"

    return _JS_IMPORT_RE.sub(_sub, body)


def _git_short_sha(repo_root: Path) -> str:
    """Short git SHA of ``HEAD``, captured once at construction.

    Returns ``"unknown"`` when git isn't available — e.g. the project was
    deployed from a tarball rather than a clone. The pythonw tray has no
    console, so the shared ``NO_WINDOW`` flag + ``stdin=DEVNULL`` keep a
    stray cmd from flashing and dodge the invalid-handle trap a console-less
    parent can hit before git even runs.
    """
    cmd = ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"⚠️  git SHA unavailable ({type(exc).__name__}: {exc})")
        return "unknown"
    sha = (result.stdout or "").strip()
    if not sha:
        logger.warning(
            "⚠️  git rev-parse exit=%s stderr=%r",
            result.returncode,
            (result.stderr or "").strip(),
        )
        return "unknown"
    return sha


class BuildInfo:
    """Immutable build identity, computed once at webapp startup."""

    def __init__(self, static_dir: Path, repo_root: Path) -> None:
        self._static_dir = static_dir
        self.asset_hashes: Dict[str, str] = compute_asset_hashes(static_dir)
        self.fleet_hash: str = fleet_hash_of(self.asset_hashes)
        self.git_sha: str = _git_short_sha(repo_root)
        self.built_at: str = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

    def stamp_html(self, html: str) -> str:
        """Stamp the asset URLs in index.html with the fleet hash."""
        return rewrite_index_html(html, self.asset_hashes)

    def stamp_js(self, body: str, source_path: Path) -> str:
        """Stamp the relative ``import`` URLs in a served JS module.

        ``source_path`` is the on-disk path of the file being served —
        its directory relative to the static root resolves ``./`` and
        ``../`` specifiers against the hash map.
        """
        try:
            rel_parent = source_path.resolve().relative_to(
                self._static_dir.resolve()
            ).parent
        except ValueError:
            rel_parent = Path(".")
        from_dir = "" if rel_parent == Path(".") else rel_parent.as_posix()
        return rewrite_js_imports(body, self.asset_hashes, from_dir)

    def as_dict(self) -> Dict[str, str]:
        """Payload for the ``/api/version`` endpoint."""
        return {
            "git_sha": self.git_sha,
            "built_at": self.built_at,
            "asset_hash": self.fleet_hash or "missing",
        }
