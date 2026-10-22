"""Structural check (#502, recurring `bug` audit bucket): a ``setInterval`` poll
callback must never unconditionally rebuild a DOM region that (directly or via
a function it calls) creates a live ``<input>``. Doing so discards whatever
the user is mid-typing — and steals focus — on the very next tick. That is
the exact shape the Time poll had: its 15 s refresh called ``renderTimer()``
bare, which calls ``tick()``, which (re)builds the "Minutes to save" input
that corrects a forgotten timer before stopping it.

This walks every static JS file rather than special-casing ``time.js``, so
the next poll-driven rebuild of a live input trips it too. It fails against
the pre-fix source (``git stash`` reproduces the bare
``renderGlance(); renderTimer();`` call) and passes once the call is gated on
whether the thing being rendered actually changed.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "webapp" / "static"

_FUNCTION_DEF = re.compile(r"(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{")
_SET_INTERVAL_INLINE = re.compile(r"window\.setInterval\(\s*function\s*\([^)]*\)\s*\{")
_BUILDS_INPUT = re.compile(r"el\(\s*['\"]input\b")

# Tokens after which a leading `/` opens a regex literal rather than meaning
# division — covers everything this codebase actually uses (`.match(/^x/)`,
# `return /x/`, etc.). Division always follows an identifier/number/`)`/`]`,
# none of which appear here, so this stays unambiguous without a real parser.
_REGEX_CONTEXT_PUNCT = set("([{,;:=!&|?+-*%^~<>\n")
_REGEX_CONTEXT_WORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "yield",
    "case", "do", "else", "delete", "void", "throw",
}


def _mask_non_code(src: str) -> str:
    """Blank out comments, string/template literals, and regex literals
    (preserving length, so offsets stay valid) before brace-counting —
    otherwise a literal brace inside any of those (e.g. the regex `/^\\{/`)
    desyncs naive brace matching on a file that has nothing to do with this
    check's actual target."""
    out: list[str] = []
    n = len(src)
    i = 0
    last_char = ""
    last_word = ""
    while i < n:
        two = src[i : i + 2]
        ch = src[i]
        if two == "//":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue
        if two == "/*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(" " * (j - i))
            i = j
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            j = i + 1
            while j < n and src[j] != quote:
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(" " * (j - i))
            last_char = quote
            i = j
            continue
        if ch == "/" and (last_char in _REGEX_CONTEXT_PUNCT or last_word in _REGEX_CONTEXT_WORDS or last_char == ""):
            j = i + 1
            closed = False
            in_class = False  # inside `[...]` a bare `/` doesn't end the regex
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    closed = True
                    j += 1
                    break
                j += 1
            if closed:
                while j < n and src[j].isalpha():
                    j += 1
                out.append(" " * (j - i))
                last_char = "/"
                last_word = ""
                i = j
                continue
        out.append(ch)
        if ch.isspace():
            pass
        elif ch.isalnum() or ch == "_":
            last_word = (last_word + ch) if last_char.isalnum() or last_char == "_" else ch
            last_char = ch
        else:
            last_word = ""
            last_char = ch
        i += 1
    return "".join(out)


def _brace_body(src: str, masked: str, open_brace_pos: int) -> str:
    """Text from `open_brace_pos` (a `{`) through its matching `}`, inclusive —
    walked over `masked` (comments/strings/regex blanked) but sliced from the
    real `src` so callers still see genuine code."""
    depth = 0
    for i in range(open_brace_pos, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_brace_pos : i + 1]
    raise AssertionError(f"unbalanced braces from offset {open_brace_pos}")


def _function_bodies(src: str, masked: str) -> dict[str, str]:
    return {m.group(1): _brace_body(src, masked, m.end() - 1) for m in _FUNCTION_DEF.finditer(masked)}


def _poll_bodies(src: str, masked: str) -> list[str]:
    return [_brace_body(src, masked, m.end() - 1) for m in _SET_INTERVAL_INLINE.finditer(masked)]


def _calls(body: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(name) + r"\s*\(", body) is not None


def _input_building_functions(functions: dict[str, str]) -> set[str]:
    """Functions that build an `<input>` directly, or transitively through
    another function they call — e.g. ``renderTimer`` calling ``tick``."""
    builders = {name for name, body in functions.items() if _BUILDS_INPUT.search(body)}
    changed = True
    while changed:
        changed = False
        for name, body in functions.items():
            if name in builders:
                continue
            if any(_calls(body, target) for target in builders):
                builders.add(name)
                changed = True
    return builders


def _is_guarded(poll_body: str, call_start: int) -> bool:
    """True if the call at `call_start` is reached only through an `if`,
    rather than unconditionally on every poll tick. Looks back to the last
    statement boundary (`;`, `{`, or `}`) and checks for an `if (` in between —
    covers both ``if (x) call();`` and ``if (x) { ... call(); }``."""
    boundary = max(poll_body.rfind(c, 0, call_start) for c in ";{}")
    preceding = poll_body[boundary + 1 : call_start]
    return "if" in preceding and "(" in preceding


def test_no_poll_unconditionally_rebuilds_a_live_input_field():
    offenders: list[str] = []
    for path in sorted(STATIC_DIR.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        masked = _mask_non_code(src)
        functions = _function_bodies(src, masked)
        input_builders = _input_building_functions(functions)
        if not input_builders:
            continue
        for poll_body in _poll_bodies(src, masked):
            for name in input_builders:
                for call_m in re.finditer(r"\b" + re.escape(name) + r"\s*\(\s*\)", poll_body):
                    if not _is_guarded(poll_body, call_m.start()):
                        offenders.append(
                            f"{path.name}: `{name}()` rebuilds a live <input> but is called "
                            "unconditionally from a setInterval poll — it will discard "
                            "in-progress typing on the next tick"
                        )
    assert not offenders, "\n".join(offenders)
