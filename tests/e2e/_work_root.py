"""Where one e2e run keeps its files, and how the gallery stays path-independent.

Stories 06, 09, 10 and 24 put absolute paths on screen. A run's root carries a
per-run token so two runs from two checkouts at the same time never share a
folder, which would otherwise rewrite those shots on every run. ``shot()``
therefore paints ``E2E_SHARED_ROOT`` in place of the run's own root
(``path_mask_rules`` + ``MASK_PATHS_JS``): the gallery stays byte-identical
whichever checkout, and whichever run, took the picture.

The root stays under the system drive's temp-like area on purpose: a repo-local
root put the SQLite file on the checkout's own drive and slowed writes enough
to lose races the stories were already winning only narrowly. On Windows the
base is the all-users Public folder, not the system temp dir: temp sits inside
the user profile, so a path put on screen would carry the account name of
whoever ran the suite into a public gallery. Public is on the same system drive
as temp, so the write speed holds, and its path names no one.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import tempfile
from pathlib import Path


def work_root_base() -> Path:
    public = os.environ.get("PUBLIC") if sys.platform == "win32" else None
    return Path(public) if public and Path(public).is_dir() else Path(tempfile.gettempdir())


#: Where every e2e run on this machine keeps its own root, and the one file
#: they all share (the boot lock).
E2E_SHARED_ROOT = work_root_base() / "taskos-e2e"

#: How a pytest-xdist worker learns the root its controller named. Workers are
#: spawned after the controller imports this module, so they inherit it.
RUN_ROOT_ENV = "TASKOS_E2E_RUN_ROOT"


def resolve_work_root() -> Path:
    """This run's own root: the controller's, handed down by env, else a fresh one.

    Only the name is made here; the directory appears with its first instance,
    so a collect-only run leaves nothing behind.
    """
    inherited = os.environ.get(RUN_ROOT_ENV)
    if inherited:
        return Path(inherited)
    root = E2E_SHARED_ROOT / f"run-{secrets.token_hex(4)}"
    os.environ[RUN_ROOT_ENV] = str(root)
    return root


E2E_WORK_ROOT = resolve_work_root()


def path_mask_rules(work_root: Path, shared_root: Path) -> list[list[str]]:
    """``[regex, replacement]`` pairs that turn a run's root into the shared one.

    Both slash forms, matched without regard to case as Windows paths are.
    """
    return [
        [re.escape(str(work_root)), str(shared_root)],
        [re.escape(work_root.as_posix()), shared_root.as_posix()],
    ]


#: Swaps the rules into every text node and text field, and leaves
#: ``window.__taskosPathUnmask`` to put the page back as it was.
MASK_PATHS_JS = """
(rules) => {
  const res = rules.map(([src, to]) => [new RegExp(src, 'gi'), to]);
  const swap = (s) => res.reduce((acc, [re, to]) => acc.replace(re, () => to), s);
  const undo = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const was = n.nodeValue, now = swap(was);
    if (now !== was) { n.nodeValue = now; undo.push(() => { n.nodeValue = was; }); }
  }
  for (const el of document.querySelectorAll('input, textarea')) {
    const was = el.value, now = swap(was || '');
    if (now === was) continue;
    // Assigning a value drops the field's selection, which a shot may be showing.
    const put = (v) => {
      let sel = null;
      try { sel = [el.selectionStart, el.selectionEnd, el.selectionDirection]; } catch (e) { /* not a text field */ }
      el.value = v;
      if (sel && sel[0] !== null && document.activeElement === el) {
        const at = (i) => Math.min(i, v.length);
        el.setSelectionRange(at(sel[0]), at(sel[1]), sel[2]);
      }
    };
    put(now);
    undo.push(() => put(was));
  }
  window.__taskosPathUnmask = () => { undo.forEach((f) => f()); delete window.__taskosPathUnmask; };
}
"""
