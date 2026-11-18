"""``format.js`` helpers behind the drawer's compact comment rows.

``fmtCommentWhen`` is the narrow time column and ``singleLink`` decides whether a
comment is its own link: both are hand-kept JS the unit tier loads under node.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.node_js import CALL_RUNNER, call_js, requires_node

MODULE = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "format.js"

pytestmark = requires_node

# A local noon, so no timezone shifts a timestamp across midnight.
NOW = "new Date(2026, 10, 19, 12, 0, 0)"


def _when(iso_parts: list[int]) -> str:
    runner = f"""
const mod = await import(process.argv[1]);
const at = (p) => new Date(p[0], p[1], p[2], p[3], p[4]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([p]) => mod.fmtCommentWhen(at(p).toISOString(), {NOW}));
process.stdout.write(JSON.stringify(out));
"""
    return call_js(MODULE, runner, [[iso_parts]])[0]


def test_the_time_column_reads_time_today_yest_then_a_short_date() -> None:
    assert _when([2026, 10, 19, 9, 5]) == "09:05"
    assert _when([2026, 10, 18, 23, 59]) == "Yest."
    assert _when([2026, 10, 17, 8, 0]) == "17 Nov"
    assert _when([2026, 0, 3, 8, 0]) == "3 Jan"
    assert _when([2025, 11, 31, 8, 0]) == "31 Dec 25"


def _single(*texts: str) -> list:
    return call_js(MODULE, CALL_RUNNER, [["singleLink", [t]] for t in texts])


def test_a_comment_is_its_own_link_only_with_exactly_one_plain_web_link() -> None:
    one, only, two, folder, mixed, ai, issue, punct = _single(
        "Office booked, details at https://example.com/x/1 — bring photos",
        "https://example.com/x/1",
        "See https://example.com/a and https://example.com/b",
        "Plans in {onedrive}/house",
        "Plans in {onedrive}/house and https://example.com/a",
        "Chat https://claude.ai/chat/abc123 notes",
        "Tracked in owner/repo#12 and https://example.com/a",
        "Read https://example.com/a.",
    )
    assert one == {"url": "https://example.com/x/1", "rest": "Office booked, details at — bring photos"}
    assert only == {"url": "https://example.com/x/1", "rest": ""}
    assert two is None and folder is None and mixed is None and ai is None and issue is None
    assert punct == {"url": "https://example.com/a", "rest": "Read."}
