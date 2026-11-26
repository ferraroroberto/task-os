"""Task search ranks exact matches first, then partial, typo-tolerant and, failing all, closest ones."""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from src import tasks_repo as repo
from src.tasks.search import CLOSEST_LIMIT, CLOSEST_OPEN, split_terms


def _ids(hits: list[dict]) -> list[int]:
    return [h["id"] for h in hits]


def _kinds(hits: list[dict]) -> dict[int, str]:
    return {h["id"]: h["match_kind"] for h in hits}


def test_split_terms_breaks_joiners_and_keeps_a_decimal_whole() -> None:
    assert split_terms("017-052") == ["017", "052"]
    assert split_terms("garden-bot#12 a/b_c") == ["garden", "bot", "12", "a", "b", "c"]
    assert split_terms("0.17-0.52") == ["0.17", "0.52"]
    assert split_terms("Milk milk MILK") == ["Milk"]
    assert split_terms('  "quo:tes" --- ') == ["quo", "tes"]
    assert split_terms("---") == [] and split_terms("") == []
    assert len(split_terms(" ".join(f"w{i}" for i in range(20)))) == 8


def test_a_joined_number_range_finds_both_parts_in_any_order_and_the_exact_one_first(
    conn: sqlite3.Connection,
) -> None:
    far = repo.create_task(conn, "Receipt 052 filed under batch 017 later")
    reversed_ = repo.create_task(conn, "Totals", description="values 052 then 017")
    exact = repo.create_task(conn, "Range 017-052 checked")
    only_one = repo.create_task(conn, "Just 017 here")
    repo.create_task(conn, "Unrelated errand")

    hits = repo.search(conn, "017-052")

    assert _ids(hits)[0] == exact["id"]
    assert set(_ids(hits)[:3]) == {exact["id"], far["id"], reversed_["id"]}
    assert _kinds(hits) == {
        exact["id"]: "exact", far["id"]: "exact", reversed_["id"]: "exact", only_one["id"]: "partial",
    }
    assert _ids(hits)[-1] == only_one["id"]


def test_a_decimal_also_matches_without_its_dot(conn: sqlite3.Connection) -> None:
    dotted = repo.create_task(conn, "Ratio 0.17 measured")
    plain = repo.create_task(conn, "Code 017 listed")
    repo.create_task(conn, "Code 018 listed")

    assert set(_ids(repo.search(conn, "0.17"))) == {dotted["id"], plain["id"]}
    both = repo.create_task(conn, "Range 0.17-0.52 measured")
    no_dots = repo.create_task(conn, "Range 017 and 052 listed")
    hits = repo.search(conn, "0.17-0.52")
    assert _ids(hits)[0] == both["id"]
    assert _kinds(hits)[no_dots["id"]] == "exact"


def test_two_words_find_a_task_holding_both_in_any_order_and_place(conn: sqlite3.Connection) -> None:
    in_title = repo.create_task(conn, "Order a ladder for the garden")
    in_desc = repo.create_task(conn, "Garden job", description="we need a ladder")
    split_places = repo.create_task(conn, "Ladder shopping")
    repo.add_comment(conn, split_places["id"], "check the garden shed first")
    in_comments = repo.create_task(conn, "Other")
    repo.add_comment(conn, in_comments["id"], "garden notes")
    repo.add_comment(conn, in_comments["id"], "borrow a ladder")
    only_garden = repo.create_task(conn, "Garden tidy")

    hits = repo.search(conn, "ladder garden")

    assert {h["id"] for h in hits if h["match_kind"] == "exact"} == {
        in_title["id"], in_desc["id"], split_places["id"], in_comments["id"],
    }
    assert _kinds(hits)[only_garden["id"]] == "partial"


def test_a_missing_word_still_returns_the_other_words_below_full_matches(
    conn: sqlite3.Connection,
) -> None:
    full = repo.create_task(conn, "Renew passport at the consulate")
    one_of_two = repo.create_task(conn, "Passport photos")
    other = repo.create_task(conn, "Consulate opening hours")
    repo.create_task(conn, "Nothing alike")

    hits = repo.search(conn, "passport consulate")
    assert _ids(hits)[0] == full["id"]
    assert _kinds(hits) == {full["id"]: "exact", one_of_two["id"]: "partial", other["id"]: "partial"}

    # a word that is nowhere in the database does not empty the result
    hits = repo.search(conn, "passport zzzzqq")
    assert {h["id"] for h in hits} == {full["id"], one_of_two["id"]}
    assert {h["match_kind"] for h in hits} == {"partial"}


def test_partial_needs_half_of_the_terms_and_more_matches_rank_higher(conn: sqlite3.Connection) -> None:
    three = repo.create_task(conn, "alpha beta gamma extra")
    two = repo.create_task(conn, "alpha beta other")
    one = repo.create_task(conn, "alpha alone")

    hits = repo.search(conn, "alpha beta gamma delta")
    assert _ids(hits) == [three["id"], two["id"]]       # 3 of 4, 2 of 4; 1 of 4 stays out
    assert one["id"] not in _ids(hits)
    assert {h["match_kind"] for h in hits} == {"partial"}


def test_a_one_letter_typo_finds_the_task_below_the_exact_ones(conn: sqlite3.Connection) -> None:
    typo_task = repo.create_task(conn, "Renew passport")
    literal = repo.create_task(conn, "Note: pasport spelled wrong in the form")

    hits = repo.search(conn, "pasport")

    assert _kinds(hits) == {literal["id"]: "exact", typo_task["id"]: "similar"}
    assert _ids(hits) == [literal["id"], typo_task["id"]]
    similar = hits[1]
    assert similar["matched_in"] == "title" and similar["snippet"] == "Renew [passport]"


@pytest.mark.parametrize("typo", ["pasport", "passprt", "passsport", "pssport", "passpotr"])
def test_typo_shapes_are_tolerated(conn: sqlite3.Connection, typo: str) -> None:
    t = repo.create_task(conn, "Renew passport")
    assert _ids(repo.search(conn, typo)) == [t["id"]]


def test_a_typo_in_one_word_of_a_phrase_keeps_the_task(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Renew passport online")
    repo.create_task(conn, "Renew library card")

    hits = repo.search(conn, "pasport online")

    assert _ids(hits)[0] == t["id"]


def test_the_fuzzy_tier_leaves_noise_out(conn: sqlite3.Connection) -> None:
    repo.create_task(conn, "Renew passport")
    repo.create_task(conn, "Buy a boat")
    repo.create_task(conn, "Ticket 123457")
    repo.create_task(conn, "The cat sat")
    # two edits on a seven-letter word, an unrelated word, a number off by a digit, three
    # letters: none is a typo match, so each can only come back as the closest guess
    for q in ("pxsspxrt", "garage", "123456", "cut"):
        assert {h["match_kind"] for h in repo.search(conn, q)} == {"closest"}, q


def test_longer_words_tolerate_two_edits(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Schedule infrastructure review")
    assert _ids(repo.search(conn, "infrastrucure")) == [t["id"]]        # one edit
    assert _ids(repo.search(conn, "infrastrukture")) == [t["id"]]       # one substitution
    assert _ids(repo.search(conn, "infrastrukcure")) == [t["id"]]       # two edits


def test_exact_matches_always_rank_above_partial_and_similar(conn: sqlite3.Connection) -> None:
    similar = repo.create_task(conn, "Plan the kitchne refit")          # near "kitchen"
    partial = repo.create_task(conn, "Kitchen tiles")
    exact = repo.create_task(conn, "Kitchen refit quote")
    for i in range(3):
        repo.create_task(conn, f"Kitchen refit filler {i}")

    hits = repo.search(conn, "kitchen refit")
    order = [h["match_kind"] for h in hits]

    assert order == sorted(order, key=("exact", "partial", "similar").index)
    assert "closest" not in order                      # the stricter tiers found something
    assert hits[0]["match_kind"] == "exact"
    assert _kinds(hits)[partial["id"]] == "partial"
    assert _kinds(hits).get(similar["id"]) in ("partial", "similar")
    assert exact["id"] in _ids(hits)[:5]


def test_the_similar_tier_only_runs_when_the_stricter_ones_leave_room(conn: sqlite3.Connection) -> None:
    for i in range(3):
        repo.create_task(conn, f"Passport check {i}")
    repo.create_task(conn, "Pasport typo task")

    full = repo.search(conn, "passport", limit=3)
    assert {h["match_kind"] for h in full} == {"exact"}
    wider = repo.search(conn, "passport", limit=10)
    assert [h["match_kind"] for h in wider].count("similar") == 1


def test_exact_only_leaves_out_partial_and_similar_hits(conn: sqlite3.Connection) -> None:
    both = repo.create_task(conn, "Passport photos and consulate")
    repo.create_task(conn, "Passport photos")
    repo.create_task(conn, "Renew pasport")

    assert _ids(repo.search(conn, "passport consulate", exact_only=True)) == [both["id"]]
    assert [t["id"] for t in repo.list_tasks(conn, q="passport consulate")] == [both["id"]]


def test_the_vocab_view_does_not_touch_the_stored_schema(conn: sqlite3.Connection) -> None:
    repo.create_task(conn, "Renew passport")
    before = conn.execute("SELECT group_concat(name) FROM sqlite_master").fetchone()[0]
    repo.search(conn, "pasport")
    assert conn.execute("SELECT group_concat(name) FROM sqlite_master").fetchone()[0] == before


def test_search_follows_edits_for_the_fuzzy_tier(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Renew passport")
    assert _ids(repo.search(conn, "pasport")) == [t["id"]]
    repo.update_task(conn, t["id"], title="Renew licence")
    assert "similar" not in _kinds(repo.search(conn, "pasport")).values()
    repo.delete_task(conn, t["id"])
    assert repo.search(conn, "licence") == []


def test_a_query_matching_nothing_lists_the_closest_tasks(conn: sqlite3.Connection) -> None:
    near = repo.create_task(conn, "Renew passport")
    further = repo.create_task(conn, "Water the garden")
    repo.update_task(conn, near["id"], status="done")      # every status: the client filters

    hits = repo.search(conn, "pxsspxrt")

    assert _ids(hits)[0] == near["id"] and further["id"] != near["id"]
    assert {h["match_kind"] for h in hits} == {"closest"}
    assert hits[0]["matched_in"] == "title" and "[passport]" in hits[0]["snippet"]
    # the filter boxes keep "every word": no guessing there
    assert repo.search(conn, "pxsspxrt", exact_only=True) == []
    assert repo.list_tasks(conn, q="pxsspxrt") == []
    # not one letter in common with any word: there is no closest one
    assert repo.search(conn, "日本語") == []


def test_closest_is_capped_and_orders_by_likeness(conn: sqlite3.Connection) -> None:
    for i in range(30):
        repo.create_task(conn, f"Water the garden {i}")
    best = repo.create_task(conn, "Gardener visit")
    repo.create_task(conn, "Order paint")

    hits = repo.search(conn, "gxrdxnxr")

    assert len(hits) == CLOSEST_LIMIT == 20
    assert _ids(hits)[0] == best["id"]
    assert len(repo.search(conn, "gxrdxnxr", limit=8)) == 8


def test_closest_keeps_places_for_open_tasks(conn: sqlite3.Connection) -> None:
    """The Search tab shows open tasks unless asked: better-matching done ones must not take every place."""
    for i in range(30):
        done = repo.create_task(conn, f"Gardener visit {i}")
        repo.update_task(conn, done["id"], status="done")
    still_open = {repo.create_task(conn, f"Water the garden {i}")["id"] for i in range(15)}

    hits = repo.search(conn, "gxrdxnxr")

    assert len(hits) == CLOSEST_LIMIT
    assert len(still_open & set(_ids(hits))) == CLOSEST_OPEN
    assert hits[0]["status"] == "done"                 # still ordered by likeness
    assert set(_ids(hits[-CLOSEST_OPEN:])) == still_open & set(_ids(hits))


def test_closest_stays_out_when_any_stricter_tier_hit(conn: sqlite3.Connection) -> None:
    repo.create_task(conn, "Renew passport")
    repo.create_task(conn, "Water the garden")
    for q in ("passport", "passport zzzzqq", "pasport"):
        assert "closest" not in _kinds(repo.search(conn, q)).values(), q


@pytest.mark.parametrize(
    "q", ['"', "'", "AND", "OR NOT", "a*", "(x", "x)", "NEAR(a b)", "col:val", "-", "²", "日本語", "\\"]
)
def test_odd_queries_never_break_the_match_grammar(conn: sqlite3.Connection, q: str) -> None:
    repo.create_task(conn, "Plain task")
    assert isinstance(repo.search(conn, q), list)


def test_a_search_on_a_real_sized_database_stays_fast(conn: sqlite3.Connection) -> None:
    words = ["kitchen", "garden", "passport", "invoice", "report", "ladder", "review", "budget", "school", "travel"]
    for i in range(3000):
        a, b, c = words[i % 10], words[(i * 7 + 3) % 10], words[(i * 3 + 1) % 10]
        conn.execute(
            "INSERT INTO tasks(title, description, status, priority, type, created_at, updated_at) "
            "VALUES (?, ?, 'todo', 'none', 'task', 't', 't')",
            (f"{a} {b} item {i}", f"notes on {c} number {i:04d}-{i + 1:04d}"),
        )
    conn.commit()
    start = time.perf_counter()
    queries = ("017-052", "kitchen garden", "pasport", "a b c", "xqzvwk")
    for q in queries:
        repo.search(conn, q)
    assert (time.perf_counter() - start) / len(queries) < 0.5


def test_a_long_nonsense_query_stays_fast_over_a_big_vocabulary(conn: sqlite3.Connection) -> None:
    """The closest tier's worst case: eight terms, none anywhere, over some 24,000 distinct words."""
    rng = random.Random(880)

    def word() -> str:
        return "".join(rng.choice("abcdefghilmnoprstuv") for _ in range(rng.randint(4, 10)))

    conn.executemany(
        "INSERT INTO tasks(title, description, status, priority, type, created_at, updated_at) "
        "VALUES (?, ?, 'todo', 'none', 'task', 't', 't')",
        [(f"{word()} {word()} {word()}", " ".join(word() for _ in range(5))) for _ in range(3000)],
    )
    conn.commit()
    start = time.perf_counter()
    hits = repo.search(conn, "xqzvwk jqkzw wyxqz zzqxj kwxyq qjxzv yqkwz xwjqy")
    assert time.perf_counter() - start < 1.0
    assert len(hits) <= CLOSEST_LIMIT
