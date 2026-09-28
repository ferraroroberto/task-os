"""Pull the JSON payload out of a chat model's reply (#262).

Open-weight models wrap the answer they were asked for in things that are not
part of it: a ``<think>`` block (Qwen-family templates), a Markdown fence, or a
sentence of preamble. ``response_format`` cannot prevent that on these backends
(a grammar clash with the thinking prefix), so every JSON-returning caller
unwraps the reply here — one helper, so a fix lands for all of them.
"""

from __future__ import annotations

import re

#: Qwen-family templates emit a thinking block before the answer.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
#: ```json … ``` — the other thing a chat model wraps JSON in.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def json_payload(raw: str) -> str:
    """The JSON object inside a model reply: thinking block and fence removed.

    An unfenced reply that still has a preamble yields the outermost braces.
    Nothing JSON-shaped comes back as-is (stripped), for the caller's own
    ``json.loads`` to fail on.
    """
    text = _THINK_RE.sub("", raw or "").strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


__all__ = ["json_payload"]
