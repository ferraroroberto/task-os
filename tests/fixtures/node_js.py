"""Load one of the web app's ES modules under node and call it from a test.

The hand-kept JS (``actions.js``, ``filters.js``, ``swipe.js``, ``recurrence.js``)
has no browser in the unit tier, so each parity test sends ``[[call, …], …]`` on
stdin to a tiny runner script and reads one JSON array back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

NODE = shutil.which("node")

#: Module-level ``pytestmark`` for a test file that needs node.
requires_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")


#: The runner for a module of plain functions: reads ``[[fn, args], …]`` on
#: stdin, prints each ``mod[fn](...args)`` as one JSON array.
CALL_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, args]) => mod[fn](...args));
process.stdout.write(JSON.stringify(out));
"""


def call_js(module: Path, runner: str, calls: list) -> list:
    """Run ``runner`` (an ES-module script reading ``process.argv[1]``) over ``calls``."""
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", runner, module.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)
