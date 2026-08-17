#!/usr/bin/env python3
"""
Folder Searcher core - all logic that does not need a GUI.

This module owns the testable half of the tool:

- Root normalization and legacy ``root_folder`` migration
- Multi-root scanning into a single index
- Sectioned index persistence (with legacy-format fallback)
- Absolute result records
- Search matching
- Path-depth display
- Email-branch pruning

Nothing here imports ``tkinter``, ``pystray`` or any ``win32`` module, so the
whole surface is importable and testable from a plain interpreter.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Defaults applied when a key is absent from the config file.
DEFAULT_SKIP_DEPTH = 4
DEFAULT_PRUNE_EMAIL_BRANCHES = True

# A folder is treated as a contact folder when its name is an email address:
# a non-empty local part, an "@", and a domain carrying a dotted TLD. The
# dotted-TLD requirement is what keeps names like "cl@ve" and "@vscode" out.
EMAIL_FOLDER_RE = re.compile(r"^[^@\s\\/]+@[^@\s\\/]+\.[A-Za-z]{2,}$")

# Marker introducing a root section in the index file.
_ROOT_PREFIX = "Root: "
# Indent marking a child entry under the current folder line.
_CHILD_INDENT = "  "


def normalize_root(path: str) -> str:
    """Normalize a single root path to its canonical stored form.

    Returns an absolute path with forward slashes and no trailing separator,
    so that the same folder typed three different ways compares equal.
    """
    if not path or not path.strip():
        return ""
    expanded = os.path.expandvars(os.path.expanduser(path.strip()))
    absolute = os.path.abspath(expanded)
    normalized = absolute.replace("\\", "/")
    # Keep the trailing slash on a drive root ("E:/"), strip it elsewhere.
    if len(normalized) > 3 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def normalize_roots(paths: Iterable[str]) -> List[str]:
    """Normalize a list of roots, dropping blanks and duplicates.

    Order is preserved: the first occurrence of each distinct root wins.
    """
    seen = set()
    result: List[str] = []
    for path in paths or []:
        normalized = normalize_root(path)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def join_path(parent: str, name: str) -> str:
    """Join a normalized parent with a child name.

    A drive root normalizes to "E:/" (the trailing slash is significant
    there), so a naive f"{parent}/{name}" would yield "E://foo" while the
    walk key for that same folder is "E:/foo" — two spellings of one path,
    which shows up as duplicate result rows.
    """
    return f"{parent.rstrip('/')}/{name}"


def is_email_folder_name(name: str) -> bool:
    """True when a folder's own name looks like an email address."""
    return bool(EMAIL_FOLDER_RE.match(name.strip()))


@dataclass(frozen=True)
class SearchResult:
    """One row in the result list.

    ``absolute_path`` is what gets opened; ``display_path`` is what the user
    reads. They differ only by the leading components ``skip_depth`` trims.
    """

    absolute_path: str
    display_path: str


@dataclass
class FolderSearcherConfig:
    """Parsed ``foldersearcher.json``."""

    root_paths: List[str]
    structure_file: str
    skip_depth: int = DEFAULT_SKIP_DEPTH
    prune_email_branches: bool = DEFAULT_PRUNE_EMAIL_BRANCHES

    @classmethod
    def from_dict(cls, data: Dict, structure_file: str) -> "FolderSearcherConfig":
        """Build a config from raw JSON, migrating the legacy schema.

        Pre-multi-root configs carry a single ``root_folder`` string. It is
        promoted to a one-element ``root_paths`` list. When both keys are
        present, ``root_paths`` wins and the legacy value is folded in after
        it, so no configured root is silently dropped.
        """
        raw_roots: List[str] = []

        listed = data.get("root_paths")
        if isinstance(listed, str):
            raw_roots.append(listed)
        elif isinstance(listed, (list, tuple)):
            raw_roots.extend(str(item) for item in listed)

        legacy = data.get("root_folder")
        if isinstance(legacy, str) and legacy.strip():
            raw_roots.append(legacy)
            if listed is None:
                logger.info("Migrating legacy 'root_folder' to 'root_paths'")

        skip_depth = data.get("skip_depth", DEFAULT_SKIP_DEPTH)
        try:
            skip_depth = max(0, int(skip_depth))
        except (TypeError, ValueError):
            logger.warning("Invalid skip_depth %r, using %d", skip_depth, DEFAULT_SKIP_DEPTH)
            skip_depth = DEFAULT_SKIP_DEPTH

        prune = data.get("prune_email_branches", DEFAULT_PRUNE_EMAIL_BRANCHES)
        if not isinstance(prune, bool):
            prune = DEFAULT_PRUNE_EMAIL_BRANCHES

        return cls(
            root_paths=normalize_roots(raw_roots),
            structure_file=structure_file,
            skip_depth=skip_depth,
            prune_email_branches=prune,
        )

    def to_dict(self) -> Dict:
        """Serialize back to the on-disk schema (new keys only)."""
        return {
            "root_paths": list(self.root_paths),
            "structure_file": self.structure_file,
            "skip_depth": self.skip_depth,
            "prune_email_branches": self.prune_email_branches,
        }


def load_config(config_file: str, structure_file: str) -> FolderSearcherConfig:
    """Read a config file, falling back to defaults when it is missing."""
    if not os.path.exists(config_file):
        logger.info("No config at %s, using defaults", config_file)
        return FolderSearcherConfig(root_paths=[], structure_file=structure_file)
    try:
        with open(config_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.error("Error loading configuration: %s", exc)
        return FolderSearcherConfig(root_paths=[], structure_file=structure_file)
    if not isinstance(data, dict):
        logger.error("Configuration is not a JSON object, using defaults")
        return FolderSearcherConfig(root_paths=[], structure_file=structure_file)
    return FolderSearcherConfig.from_dict(data, structure_file)


def save_config(config_file: str, config: FolderSearcherConfig) -> None:
    """Write the config back to disk."""
    with open(config_file, "w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)
    logger.info("Configuration saved to %s", config_file)


class FolderIndex:
    """The scanned folder structure across every configured root.

    Internally this is just ``{absolute folder path: [absolute child paths]}``
    plus the ordered list of roots the entries came from. Everything the
    search needs — including which folders own a contact subfolder — is
    derivable from that, so no filesystem access happens at search time.
    """

    def __init__(self, roots: Optional[Sequence[str]] = None):
        self.roots: List[str] = list(roots or [])
        self.entries: Dict[str, List[str]] = {}

    def __len__(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, roots: Sequence[str]) -> int:
        """Walk every root, replacing the current index.

        Roots that do not exist are skipped with a warning rather than
        aborting the whole scan — one unplugged drive should not cost the
        user the other roots.

        Returns the number of folders indexed.
        """
        self.roots = normalize_roots(roots)
        self.entries = {}

        for root in self.roots:
            if not os.path.isdir(root):
                logger.warning("Skipping missing root: %s", root)
                continue
            logger.info("Scanning root: %s", root)
            for current, dirs, _files in os.walk(root):
                key = normalize_root(current)
                children = [join_path(key, name) for name in dirs]
                # os.walk yields each directory once, but a root nested
                # inside another root would revisit it — merge rather than
                # overwrite so neither pass loses children.
                if key in self.entries:
                    known = set(self.entries[key])
                    self.entries[key].extend(c for c in children if c not in known)
                else:
                    self.entries[key] = children

        logger.info("Scan complete: %d folders across %d root(s)", len(self.entries), len(self.roots))
        return len(self.entries)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, structure_file: str) -> None:
        """Write the index as explicit ``Root:`` sections."""
        with open(structure_file, "w", encoding="utf-8") as handle:
            for root in self.roots:
                handle.write(f"{_ROOT_PREFIX}{root}\n")
                prefix = root if root.endswith("/") else root + "/"
                section = sorted(
                    key for key in self.entries
                    if key == root or key.startswith(prefix)
                )
                for folder in section:
                    handle.write(f"{folder}\n")
                    for child in sorted(self.entries[folder]):
                        handle.write(f"{_CHILD_INDENT}{child}\n")
                    handle.write("\n")
        logger.info("Index saved to %s", structure_file)

    def load(self, structure_file: str, legacy_root: Optional[str] = None) -> int:
        """Read an index file, accepting both the new and legacy formats.

        A file with no ``Root:`` header is a pre-multi-root index holding
        paths relative to a single root; ``legacy_root`` is prepended to
        rebuild absolute paths. Returns the number of folders loaded.
        """
        self.roots = []
        self.entries = {}

        if not os.path.exists(structure_file):
            logger.info("No index file at %s", structure_file)
            return 0

        with open(structure_file, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()

        sectioned = any(line.startswith(_ROOT_PREFIX) for line in lines)
        if sectioned:
            self._load_sectioned(lines)
        else:
            self._load_legacy(lines, legacy_root)

        logger.info("Index loaded: %d folders across %d root(s)", len(self.entries), len(self.roots))
        return len(self.entries)

    def _load_sectioned(self, lines: Sequence[str]) -> None:
        """Parse the current format: ``Root:`` headers with absolute paths."""
        current_folder = ""
        for line in lines:
            if not line.strip():
                continue
            if line.startswith(_ROOT_PREFIX):
                root = normalize_root(line[len(_ROOT_PREFIX):])
                if root and root not in self.roots:
                    self.roots.append(root)
                current_folder = ""
                continue
            if line.startswith(_CHILD_INDENT):
                if not current_folder:
                    continue
                child = normalize_root(line[len(_CHILD_INDENT):])
                if child and child not in self.entries[current_folder]:
                    self.entries[current_folder].append(child)
            else:
                current_folder = normalize_root(line)
                self.entries.setdefault(current_folder, [])

    def _load_legacy(self, lines: Sequence[str], legacy_root: Optional[str]) -> None:
        """Parse a pre-multi-root index of root-relative paths.

        Without a ``legacy_root`` the stored paths cannot be resolved to
        anything openable, so the file is treated as empty rather than
        producing results that fail on double-click.
        """
        root = normalize_root(legacy_root or "")
        if not root:
            logger.warning("Legacy index found but no legacy root configured; ignoring it")
            return

        self.roots = [root]

        def absolutize(relative: str) -> str:
            cleaned = relative.strip().replace("\\", "/").strip("/")
            if not cleaned or cleaned == "root":
                return root
            return join_path(root, cleaned)

        current_folder = ""
        for line in lines:
            if not line.strip():
                continue
            if line.startswith(_CHILD_INDENT):
                if not current_folder:
                    continue
                child = absolutize(line[len(_CHILD_INDENT):])
                if child not in self.entries[current_folder]:
                    self.entries[current_folder].append(child)
            else:
                current_folder = absolutize(line)
                self.entries.setdefault(current_folder, [])

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------

    def all_paths(self) -> List[str]:
        """Every distinct folder path the index knows about."""
        paths = set(self.entries)
        for children in self.entries.values():
            paths.update(children)
        return sorted(paths)

    def owning_items(self) -> set:
        """Folders that have at least one direct email-named child.

        These are the "items" that email pruning collapses results onto.
        """
        owners = set()
        for folder, children in self.entries.items():
            if any(is_email_folder_name(os.path.basename(child)) for child in children):
                owners.add(folder)
        return owners


def display_path(absolute_path: str, skip_depth: int) -> str:
    """Trim the leading ``skip_depth`` components for display.

    Display-only: the caller keeps the absolute path for opening. When the
    path has no more components than the skip depth there is nothing
    meaningful left to trim, so the last component is shown rather than an
    empty string.
    """
    normalized = absolute_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if skip_depth <= 0:
        return normalized
    if len(parts) <= skip_depth:
        return parts[-1] if parts else normalized
    return "/".join(parts[skip_depth:])


def parse_search_terms(search_input: str) -> List[str]:
    """Split a raw search box value into lowercase AND-ed terms."""
    processed = (search_input or "").replace(";", " ")
    return [term.strip().lower() for term in processed.split() if term.strip()]


def prune_to_owning_items(paths: Iterable[str], owners: set) -> List[str]:
    """Collapse each path onto its shallowest owning-item ancestor.

    An owning item is a folder with a direct email-named child. Once such a
    folder is reached, it is a leaf as far as results are concerned: matches
    at or below it — across email variants and sibling branches like
    ``muestras``, ``temporal`` or ``inventario`` — all fold into that single
    row. Paths with no owning ancestor pass through unchanged.

    The shallowest ancestor wins so that nested items collapse upward to the
    outermost item, matching "that item becomes a leaf result".
    """
    if not owners:
        return sorted(set(paths))

    # Lowercase lookup: the index is case-preserving but Windows paths are
    # not case-sensitive, and roots may be typed either way.
    owners_lower = {owner.lower(): owner for owner in owners}

    collapsed = set()
    for path in paths:
        normalized = path.replace("\\", "/")
        parts = normalized.split("/")
        owner = None
        # Walk from the shallowest prefix down, stopping at the first owner.
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            match = owners_lower.get(prefix.lower())
            if match is not None:
                owner = match
                break
        collapsed.add(owner if owner is not None else path)
    return sorted(collapsed)


def search(
    index: FolderIndex,
    search_input: str,
    skip_depth: int = DEFAULT_SKIP_DEPTH,
    prune_email_branches: bool = DEFAULT_PRUNE_EMAIL_BRANCHES,
) -> List[SearchResult]:
    """Find folders whose absolute path contains every search term.

    Matching is case-insensitive and AND-ed across terms, against the full
    absolute path — so "genai guia" matches a folder whose ancestry supplies
    one term and whose own name supplies the other.
    """
    terms = parse_search_terms(search_input)
    if not terms:
        return []

    matches = [path for path in index.all_paths() if all(term in path.lower() for term in terms)]

    if prune_email_branches:
        matches = prune_to_owning_items(matches, index.owning_items())
    else:
        matches = sorted(set(matches))

    return [SearchResult(absolute_path=path, display_path=display_path(path, skip_depth)) for path in matches]
