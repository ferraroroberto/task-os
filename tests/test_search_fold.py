"""``search.js`` — the one folded line under the Search results (#395).

Search shows a group only for a kind with hits; every other kind folds into
one line, so nothing goes silent and nothing takes a card to say "nothing":
the kinds that matched nothing, the task hits the filters or the scope hid
(only when they hid them all — a partial cut is the group's "3 of 5"), and the
kinds this install has not set up (the Settings link follows on screen).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "search.js"
NODE = shutil.which("node")

_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(JSON.parse(input).map((fold) => mod.foldParts(fold))));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")


def _fold(*folds: dict) -> list[list[str]]:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(list(folds)), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_nothing_to_fold_is_no_line() -> None:
    assert _fold({}, {"none": [], "hidden": 0, "off": []}) == [[], []]


def test_each_kind_of_absence_is_named_once() -> None:
    assert _fold(
        {"none": ["Folders"]},
        {"none": ["Folders", "Issues"]},
        {"none": ["Tasks", "Folders", "Emails (index still building)"]},
    ) == [
        ["No matches in folders"],
        ["No matches in folders and issues"],
        ["No matches in tasks, folders and emails (index still building)"],
    ]


def test_hidden_task_hits_and_unset_kinds_ride_the_same_line() -> None:
    assert _fold({"none": ["Issues"], "hidden": 3, "off": ["Emails"]}) == [[
        "No matches in issues", "3 task hits hidden by the filters or the scope", "Not set up: emails",
    ]]
    assert _fold({"hidden": 1}) == [["1 task hit hidden by the filters or the scope"]]
