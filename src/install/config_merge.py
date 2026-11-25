"""Ignored configs from their committed samples, never overwriting what a PC has.

For each ``config/<name>.sample.json`` the live twin is ``config/<name>.json``:

* missing → copied from the sample (``created``);
* present and parseable → it gains the keys the sample has and it lacks, after
  a timestamped copy under ``config/backups/`` (``merged``), and every value it
  already holds stays as it is;
* present but not JSON (or not an object) → left alone and reported
  (``unparseable``).

A key is added only when the app runs exactly the same with it as without it.
Absence carries meaning in places: no ``mirror`` block means no mirror, no
``time.people`` means the implicit owner. Copying the sample's value there
would change what this PC does, which is the opposite of keeping its settings.
So each candidate key is tried against the file's own reader
(:func:`config_same_behaviour` for ``config.json``); a key that changes the
result is ``held back`` and listed, and the owner adds it by hand if wanted. A
file with no reader to prove that holds every missing key back.
"""

from __future__ import annotations

import copy
import json
import logging
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.runtime import files as runtime_files

KeyPath = tuple[str, ...]
#: ``True`` when the app reading ``after`` behaves exactly as it does reading ``before``.
SameBehaviour = Callable[[dict[str, Any], dict[str, Any]], bool]

SAMPLE_SUFFIX = ".sample.json"
BACKUP_DIR_NAME = "backups"


@dataclass(frozen=True)
class ConfigStep:
    """What happened (or, under ``-WhatIf``, would happen) to one config file.

    ``status``: ``created`` · ``merged`` · ``unchanged`` · ``unparseable``, and
    ``would-create`` · ``would-merge`` when nothing is written.
    """

    path: Path
    status: str
    added: tuple[str, ...] = ()
    held_back: tuple[str, ...] = ()
    backup: Path | None = None
    detail: str = ""


def live_name(sample: Path) -> str:
    """``config.sample.json`` → ``config.json``."""
    return sample.name[: -len(SAMPLE_SUFFIX)] + ".json"


def missing_paths(current: Mapping[str, Any], sample: Mapping[str, Any], prefix: KeyPath = ()) -> list[KeyPath]:
    """The sample's keys ``current`` lacks, each at the shallowest level it is missing."""
    found: list[KeyPath] = []
    for key, value in sample.items():
        here = (*prefix, key)
        if key not in current:
            found.append(here)
        elif isinstance(value, dict) and isinstance(current[key], dict):
            found.extend(missing_paths(current[key], value, here))
    return found


def _value_at(data: Mapping[str, Any], path: KeyPath) -> Any:
    node: Any = data
    for key in path:
        node = node[key]
    return node


def _with_key(base: dict[str, Any], path: KeyPath, value: Any) -> dict[str, Any]:
    """A copy of ``base`` with ``value`` at ``path`` (parents created as empty objects)."""
    result = copy.deepcopy(base)
    node = result
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = copy.deepcopy(value)
    return result


def plan_additions(
    current: dict[str, Any], sample: Mapping[str, Any], same: SameBehaviour,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """``current`` plus every missing key that leaves behaviour unchanged.

    A missing object that would change behaviour as a whole is tried key by
    key, so its harmless parts still arrive. Returns the merged data and the
    dotted paths added and held back.
    """
    merged = copy.deepcopy(current)
    added: list[str] = []
    held: list[str] = []

    def consider(path: KeyPath) -> None:
        nonlocal merged
        value = _value_at(sample, path)
        candidate = _with_key(merged, path, value)
        if same(merged, candidate):
            merged = candidate
            added.append(".".join(path))
        elif isinstance(value, dict) and value:
            for key in value:
                consider((*path, key))
        else:
            held.append(".".join(path))

    for path in missing_paths(current, sample):
        consider(path)
    return merged, added, held


def never_same(_before: dict[str, Any], _after: dict[str, Any]) -> bool:
    """For a file with no reader to compare: nothing can be proven harmless."""
    return False


def config_same_behaviour(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Both dicts through :func:`src.config.load_config`, compared as the app sees them."""
    from src.config import load_config

    # One scratch path for both reads: the loaded config records where it came from.
    with tempfile.TemporaryDirectory(prefix="task-os-install-") as tmp:
        path = Path(tmp) / "config.json"
        # the reader's warnings describe a scratch copy, not this PC's config
        previous = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            loaded = []
            for data in (before, after):
                runtime_files.save_text(path, json.dumps(data))
                loaded.append(load_config(path))
            return loaded[0] == loaded[1]
        finally:
            logging.disable(previous)


#: The reader that proves an added key harmless, per live config name.
READERS: dict[str, SameBehaviour] = {"config.json": config_same_behaviour}


def _read_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"not readable as JSON ({exc})"
    if not isinstance(data, dict):
        return None, f"not a JSON object (a {type(data).__name__})"
    return data, ""


def ensure_config(
    sample: Path,
    target: Path,
    *,
    whatif: bool,
    same: SameBehaviour = never_same,
    now: datetime | None = None,
) -> ConfigStep:
    """Create ``target`` from ``sample`` when missing, else add only its harmless missing keys."""
    if not target.exists():
        if whatif:
            return ConfigStep(target, "would-create", detail=f"from {sample.name}")
        runtime_files.make_dir(target.parent)
        runtime_files.copy_file(sample, target)
        return ConfigStep(target, "created", detail=f"from {sample.name}")
    current, problem = _read_object(target)
    if current is None:
        return ConfigStep(target, "unparseable", detail=f"{problem}; left untouched")
    reference, sample_problem = _read_object(sample)
    if reference is None:
        return ConfigStep(target, "unchanged", detail=f"the sample is {sample_problem}; nothing compared")
    merged, added, held = plan_additions(current, reference, same)
    if not added:
        return ConfigStep(target, "unchanged", held_back=tuple(held))
    if whatif:
        return ConfigStep(target, "would-merge", added=tuple(added), held_back=tuple(held))
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = target.parent / BACKUP_DIR_NAME / f"{target.stem}.{stamp}.json"
    runtime_files.make_dir(backup.parent)
    runtime_files.copy_file(target, backup)
    runtime_files.save_text(target, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return ConfigStep(target, "merged", added=tuple(added), held_back=tuple(held), backup=backup)


def ensure_configs(
    config_dir: Path, *, whatif: bool, now: datetime | None = None, only_existing: bool = False,
) -> list[ConfigStep]:
    """:func:`ensure_config` for every committed sample in ``config_dir``.

    ``only_existing`` leaves a missing live config alone: ``setup.bat`` creates it from its sample itself.
    """
    return [
        ensure_config(
            sample, config_dir / live_name(sample), whatif=whatif,
            same=READERS.get(live_name(sample), never_same), now=now,
        )
        for sample in sorted(config_dir.glob("*" + SAMPLE_SUFFIX))
        if not only_existing or (config_dir / live_name(sample)).exists()
    ]
