r"""Prove the story gallery is reproducible: run the e2e suite twice, diff the shots.

`docs/screenshots/` is the on-screen proof `docs/validation.md` links to, so it
is only worth anything if a change in it means a change in the app. Before #134
it did not: an animation still in flight, a pane that had not painted, and the
run's own wall clock all leaked into the files, so ~30% of them moved between
two runs of the *same* commit and a maintainer could not tell a visual
regression from capture noise.

Usage (from the repo root; each run is a full `tests/e2e` pass, ~2 min):

    & .\.venv\Scripts\python.exe -m scripts.shot_determinism
    & .\.venv\Scripts\python.exe -m scripts.shot_determinism --keep <dir>

Exit code 0 = no shot changed in any way a reader could see. Two escapes, both
narrow and both reported on every run:

* `ALLOWED_TO_DIFFER` — the named files whose *content* genuinely cannot be
  pinned, each with the reason;
* `RASTER_*` / `GLYPH_*` — a shot that differs only as this rasteriser
  differs from itself: many pixels off by `RASTER_MAX_DELTA`/255 or less along
  antialiased edges, or at most `GLYPH_MAX_PIXELS` off by `GLYPH_MAX_DELTA` or
  less, which is one icon stroke landing on the other side of a sub-pixel.
  Headless Chromium does not rasterise a card border, the nav pill's frosted
  edge or a phone-scale glyph bit-identically every time; the affected files
  change from run to run, so no per-file allowlist can express it. Nothing a
  reader can see fits under either: real UI movement shifts whole glyphs and
  edges, two hundred levels at a time.

Anything else moving is a determinism regression — the story that writes it
captured something still in flight, and the fix belongs in that story or in
`tests/e2e/conftest.py`'s `settle()`, never in these escapes.

Two runs minutes apart answer "is the capture stable?" — and, structurally,
nothing else. They cannot see the *other* drift, the one that actually bit
(#225): a gallery that no longer matches what today's code renders. Both
snapshots are fresh, so a shot that has been wrong in the repo for twenty
commits compares clean against itself. Nothing was comparing the committed
bytes, which is why 76 of them had silently drifted before anyone looked.

So there is a second mode, and it is the one the pre-ship gate runs:

    & .\.venv\Scripts\python.exe -m scripts.shot_determinism --baseline
    & .\.venv\Scripts\python.exe -m scripts.shot_determinism --check-tree

`--baseline` runs the suite once and compares what it wrote against the
gallery git already has; `--check-tree` does only the comparison, for a caller
that has just run the suite itself (the gate). Both then **restore** the tree,
so a verification run stops leaving a pile of rewritten PNGs behind for the
next person to remember to `git checkout`. The baseline is the git *index*,
which equals `HEAD` in a clean tree and deliberately lets a staged
re-baseline be the thing compared against — `git checkout --` can then never
throw staged work away.

A drift here is not capture noise and not a bug in this script: either the UI
changed and the gallery owes it a deliberate re-baseline (run `pytest
tests/e2e`, look at what moved, `git add docs/screenshots`), or something on
screen is still unpinned. Everything the app paints from a clock, a path or a
build identity is pinned for exactly this reason — see
`tests/e2e/conftest.py`'s "deterministic capture" section.

Known open flake, so far unreproduced on demand: under heavy host load, all
four of story 22's desktop shots can move together at once — thousands of
pixels, well past the raster bands above, common bbox the Board behind the
add dialog. That is real content movement, not the rasteriser. A dedicated
CPU-load harness scoped to `test_story_22_voice.py` has not reproduced the
board-wide mover; a smaller, unrelated raster excursion on the phone nav's
search icon reproduces instead at moderate load, and load pushed far enough
instead starves the disposable webapp's own boot (a timeout, not a silent
content shift) rather than reproducing it. That rules out plain CPU
contention as the trigger; what does trigger it (disk I/O? memory pressure?
a specific concurrent process?) is still unknown. Reproduce with:
`& .\.venv\Scripts\python.exe -m scripts.shot_determinism --keep <dir>` in a
loop under whatever load actually shows up next, then diff `run-1` vs `run-2`
of the four `story-22-voice-*-desktop.png` files.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"

#: Shots whose *content* legitimately cannot be pinned, with the reason. Empty
#: Story 06's instance now starts its clock at the suite's instant
#: (`TASKOS_CLOCK_TICK`) and story 09's install-command shot is framed on the
#: app's own port, so no shot is exempt from the byte-identical gallery.
ALLOWED_TO_DIFFER: dict[str, str] = {}

#: The raster-noise escape: at most this many pixels, each off by at most this
#: much on any channel. This rasteriser's actual noise floor sits at delta 2:
#: a handful of antialiased-edge pixels on story 22/23/24 shots land there and
#: clear again on the very next invocation of the same shot, none of them a
#: real content change — so delta 1 would report a clean tree as red. Delta 2
#: still leaves ~100x headroom below the smallest genuine content change
#: measured on this suite (35 px at delta 210, one digit of a timestamp) and
#: two orders of magnitude below a real regression (delta 224-225), so it
#: costs essentially no discriminating power.
RASTER_MAX_DELTA = 2
RASTER_MAX_PIXELS = 500

#: The second raster band: one antialiased **glyph edge**, not a scatter of
#: pixels. Same escape, different shape — a handful of pixels off by a lot,
#: rather than many off by a little. One glyph (the phone nav's search icon
#: at device scale factor 3, a 14x13 px box) rasterises into one of exactly
#: two stable states and which one renders is a coin toss — repeatable to the
#: pixel (28 px, worst channel delta 14) rather than noisy, so it needs its
#: own band rather than widening the raster-noise one above. Bounded hard on
#: both axes: 64 px is at most one glyph edge at DSF 3, and delta 24 is 8.75x
#: below the smallest *genuine* change ever measured on this suite (35 px at
#: delta 210, one digit of a timestamp) and roughly ten times below a real
#: regression (224-225). A difference that fits inside this is a sub-pixel
#: shift of something the size of an icon stroke; a reader cannot see it, and
#: neither can any story that asserts on the page rather than the file.
GLYPH_MAX_DELTA = 24
GLYPH_MAX_PIXELS = 64


def _visible_difference(a: Path, b: Path) -> str | None:
    """``None`` when the two files differ only as the rasteriser does, else why."""
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return f"size {ia.size} → {ib.size}"
    diff = ImageChops.difference(ia, ib)
    if diff.getbbox() is None:
        return None
    # One greyscale plane holding each pixel's *worst* channel delta, so the
    # histogram answers both questions at once — how far off, and how many.
    worst_channel = functools.reduce(ImageChops.lighter, diff.split())
    histogram = worst_channel.histogram()
    moved = sum(histogram[1:])
    worst = max(level for level, count in enumerate(histogram) if count)
    if worst <= RASTER_MAX_DELTA and moved <= RASTER_MAX_PIXELS:
        return None
    if worst <= GLYPH_MAX_DELTA and moved <= GLYPH_MAX_PIXELS:
        return None
    return f"{moved} px, worst channel delta {worst}, bbox {diff.getbbox()}"


def _run_suite(label: str) -> None:
    """One full `tests/e2e` pass, with pytest's own report kept.

    The child's output is captured rather than inherited: `CREATE_NO_WINDOW`
    gives it no console of its own, so an inherited stream reaches nothing a
    reader ever sees, and a suite that failed inside this script used to say
    only "pytest exit 1" — a red gate with the reason thrown away, which is
    how the diagnosis of #166 lost half a day. Success prints the tail (the
    counts and timing), failure prints the whole report before exiting.
    """
    env = {**os.environ, "PYTHONUTF8": "1"}
    print(f"\n=== {label}: running tests/e2e ===", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/e2e", "-q"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW,
    )
    report = ((result.stdout or "") + (result.stderr or "")).rstrip()
    if result.returncode != 0:
        print(report, flush=True)
        sys.exit(f"❌ {label} failed (pytest exit {result.returncode}) — fix the suite first")
    print("\n".join(report.splitlines()[-3:]), flush=True)


# --------------------------------------- the gallery git has vs the one on disk
# `SHOTS_REL` is how git spells the gallery: `git diff --name-only` answers in
# repo-root-relative posix paths, and `git show :<path>` takes one.
SHOTS_REL = "docs/screenshots"


def _git(*args: str) -> subprocess.CompletedProcess:
    """One `git` call against this repo, bytes out (a PNG is not text)."""
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, stdin=subprocess.DEVNULL,
        check=False, creationflags=NO_WINDOW,
    )


def _git_lines(*args: str) -> list[str]:
    result = _git(*args)
    if result.returncode != 0:
        sys.exit(f"❌ git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return [line for line in result.stdout.decode("utf-8", "replace").splitlines() if line]


def _baseline_bytes(rel: str) -> bytes | None:
    """The committed bytes of one shot — the index's copy, `HEAD`'s in a clean tree."""
    result = _git("show", f":{rel}")
    return result.stdout if result.returncode == 0 else None


def _check_against_gallery() -> int:
    """Compare the gallery on disk against the one git is holding.

    This is the comparison that was missing (#225). It only ever looks at what
    the run just rewrote — `git diff` names those — so it is as meaningful
    after a routed partial e2e slice as after a full suite, and costs nothing
    when the slice was `skip`.
    """
    total = len(list(SHOTS_DIR.glob("*.png")))
    changed = [rel for rel in _git_lines("diff", "--name-only", "--", SHOTS_REL)
               if rel.endswith(".png")]
    untracked = [rel for rel in _git_lines("ls-files", "--others", "--exclude-standard", "--", SHOTS_REL)
                 if rel.endswith(".png")]

    raster, allowed, moved = [], [], []
    with tempfile.TemporaryDirectory(prefix="taskos-gallery-baseline-") as tmp:
        for rel in changed:
            name = Path(rel).name
            if name in ALLOWED_TO_DIFFER:
                allowed.append(name)
                continue
            committed = _baseline_bytes(rel)
            if committed is None:
                moved.append((name, "git holds no copy of it"))
                continue
            if not (SHOTS_DIR / name).exists():
                moved.append((name, "git holds it, this run deleted it"))
                continue
            reference = Path(tmp) / name
            reference.write_bytes(committed)
            why = _visible_difference(reference, SHOTS_DIR / name)
            (moved if why else raster).append((name, why) if why else name)

    print(f"\n{total} shots · {total - len(changed)} byte-identical to the committed gallery · "
          f"{len(raster)} raster-noise only · {len(allowed)} on the stated allowlist · "
          f"{len(moved)} drifted · {len(untracked)} not in the gallery yet")
    for name in raster:
        print(f"  raster:  {name} (≤{RASTER_MAX_DELTA}/255 on ≤{RASTER_MAX_PIXELS} px, "
              f"or ≤{GLYPH_MAX_DELTA}/255 on ≤{GLYPH_MAX_PIXELS})")
    for name in allowed:
        print(f"  allowed: {name} — {ALLOWED_TO_DIFFER[name]}")
    for rel in untracked:
        print(f"  new:     {Path(rel).name} — no committed twin; commit it to put it in the gallery")
    for name, why in moved:
        print(f"  ❌ drifted: {name} — {why}")

    if changed:
        # Only ever tracked modifications, and only ever back to the index — an
        # untracked new shot is left exactly where the run put it.
        _git("checkout", "--", SHOTS_REL)
        print(f"\nrestored {len(changed)} rewritten shot(s) from git — the tree is as you left it")

    if moved:
        print("\n❌ the committed gallery no longer matches what this code renders.\n"
              "   Either the UI changed and the gallery owes it a deliberate re-baseline\n"
              "   (`python -m pytest tests/e2e`, review what moved, `git add docs/screenshots`),\n"
              "   or something on screen is unpinned — see tests/e2e/conftest.py's pinned inputs.")
        return 1
    print("\n✅ the committed gallery is what this code renders")
    return 0


def _snapshot(into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for png in SHOTS_DIR.glob("*.png"):
        shutil.copy2(png, into / png.name)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    # This script's own report uses ·, ≤ and ✓. Piped or redirected — which is
    # how the gate and every agent run it — Windows falls back to cp1252 and
    # `print` raises `UnicodeEncodeError` *after* the verdict has been decided,
    # turning a passing run into a traceback and a non-zero exit.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", type=Path, default=None,
                    help="directory to keep both snapshots in (default: a temp dir, removed)")
    ap.add_argument("--baseline", action="store_true",
                    help="run the suite once and compare what it writes against the committed "
                         "gallery, then restore the tree (#225)")
    ap.add_argument("--check-tree", action="store_true",
                    help="the comparison half of --baseline, for a caller that has just run the "
                         "suite itself (the pre-ship gate)")
    args = ap.parse_args()

    if args.baseline and args.check_tree:
        ap.error("--baseline already runs the suite; --check-tree is the same comparison without it")
    if args.check_tree:
        return _check_against_gallery()
    if args.baseline:
        _run_suite("baseline run")
        return _check_against_gallery()

    work = args.keep or Path(tempfile.mkdtemp(prefix="taskos-shot-determinism-"))
    first, second = work / "run-1", work / "run-2"

    _run_suite("run 1")
    _snapshot(first)
    _run_suite("run 2")
    _snapshot(second)

    names = sorted({p.name for p in first.glob("*.png")} | {p.name for p in second.glob("*.png")})
    identical, raster, allowed, moved = [], [], [], []
    for name in names:
        a, b = first / name, second / name
        if not (a.exists() and b.exists()):
            moved.append((name, "present in only one run"))
            continue
        if _digest(a) == _digest(b):
            identical.append(name)
            continue
        if name in ALLOWED_TO_DIFFER:
            allowed.append(name)
            continue
        why = _visible_difference(a, b)
        (moved if why else raster).append((name, why) if why else name)

    print(f"\n{len(names)} shots · {len(identical)} byte-identical · {len(raster)} raster-noise only · "
          f"{len(allowed)} on the stated allowlist · {len(moved)} moved")
    for name in raster:
        print(f"  raster:  {name} (≤{RASTER_MAX_DELTA}/255 on ≤{RASTER_MAX_PIXELS} px, "
              f"or ≤{GLYPH_MAX_DELTA}/255 on ≤{GLYPH_MAX_PIXELS})")
    for name in allowed:
        print(f"  allowed: {name} — {ALLOWED_TO_DIFFER[name]}")
    for name, why in moved:
        print(f"  ❌ moved: {name} — {why}")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"\nsnapshots kept under {work}")

    if moved:
        print("\n❌ the gallery is not reproducible — see tests/e2e/conftest.py::settle")
        return 1
    print("\n✅ no shot changed in any way a reader could see, across two runs of the same commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
