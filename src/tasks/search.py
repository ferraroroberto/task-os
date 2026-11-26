"""Task search: tiered lexical ranking over ``tasks_fts`` and ``comments_fts``.

A query becomes a list of **terms**: every run of letters and digits, with a
dot kept inside a run (``0.17``), so ``017-052``, ``garden-bot-12`` and
``a/b`` search for their parts in any order and any place. A decimal such as
``0.17`` also matches written without the dot (``017``). Each task lands in
one tier, and the tiers never interleave. They are the four folder-explorer
ranks folders and mails by, so every search box ranks alike:

* ``exact`` — every term matches somewhere in the title, description or a
  comment (the terms may sit in different places). A task holding the whole
  query as one adjacent phrase ranks first inside the tier, then ``bm25``.
* ``partial`` — at least half of the terms match; more matched terms first,
  then ``bm25``. Only for a query of two or more terms.
* ``similar`` — typo-tolerant: a letters-only term of four or more characters
  also matches a word in a title or description within one edit (two for
  eight or more characters) of it. Only run when the stricter tiers do not
  already fill the limit, so a good query never pays for it.
* ``closest`` — only when the three above found nothing: the
  ``CLOSEST_LIMIT`` tasks whose title or description words look most like the
  query's, scored by the mean of each term's best likeness. Half the places are
  kept for open tasks: the Search tab shows only those unless asked, and a
  database that is mostly done tasks would otherwise show an empty list.

The two weakest tiers read the words the index already holds through an
``fts5vocab`` view created in the connection's own temp schema, so it adds no
second index to keep in step and no migration (a schema bump would re-baseline
the version shown in Settings).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from typing import Any

from rapidfuzz import fuzz, process

from src.tasks.schema import CLOSED_SQL

__all__ = ["CLOSEST_LIMIT", "MATCH_CLOSEST", "MATCH_EXACT", "MATCH_PARTIAL", "MATCH_SIMILAR", "rank_tasks",
           "split_terms"]

MATCH_EXACT = "exact"
MATCH_PARTIAL = "partial"
MATCH_SIMILAR = "similar"
MATCH_CLOSEST = "closest"

#: Terms past this are ignored: each one costs two index lookups.
MAX_TERMS = 8
#: Shortest letters-only term that is typo-tolerant; shorter ones are mostly noise.
FUZZY_MIN_LEN = 4
#: From this length two edits are tolerated, below it one.
FUZZY_TWO_EDITS_LEN = 8
#: Near-words kept per term, closest then most common first, so one term cannot flood the query.
FUZZY_WORDS_PER_TERM = 12
# The closest tier's caps, folder-explorer's own values; with ``MAX_TERMS`` they
# keep a query that matches nothing quick on a slow PC.
#: Tasks it lists: enough to recognise the one meant, few enough to read.
CLOSEST_LIMIT = 20
#: Of those, the places kept for the most alike open tasks.
CLOSEST_OPEN = CLOSEST_LIMIT // 2
#: Indexed words kept per term, most alike first.
CLOSEST_WORDS = 20
#: How much longer or shorter than the term a word may be and still be compared.
CLOSEST_LENGTH_SLACK = 3
#: Tasks one closest word brings, newest first: a word thousands hold tells none of them apart.
CLOSEST_TASKS_PER_WORD = 200

_PART = re.compile(r"[^\W_]+(?:\.[^\W_]+)*")
_DECIMAL = re.compile(r"\d+(?:\.\d+)+")

# unicode61 folds case and diacritics; a fuzzy term is folded the same way so it
# compares like for like against the index's words.
_MARKS = "Mn"


def split_terms(q: str) -> list[str]:
    """The query's terms, first spelling kept, repeats dropped, capped at ``MAX_TERMS``."""
    seen: set[str] = set()
    out: list[str] = []
    for part in _PART.findall(q or ""):
        key = part.casefold()
        if key not in seen:
            seen.add(key)
            out.append(part)
    return out[:MAX_TERMS]


def _term_expr(term: str) -> str:
    """The FTS5 expression for one term: a quoted prefix phrase, plus the dot-less
    spelling of a decimal. Only letters, digits and dots reach it, so quoting is safe.

    A one-character term is the whole word, not a prefix: ``a*`` matches most of the
    index and makes every snippet lookup that much slower for no better a result."""
    star = "*" if len(term) > 1 else ""
    expr = f'"{term}"{star}'
    if _DECIMAL.fullmatch(term):
        expr = f'({expr} OR "{term.replace(".", "")}"*)'
    return expr


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != _MARKS)


def _task_ids(conn: sqlite3.Connection, expr: str, *, comments: bool = True) -> set[int]:
    ids = {int(r[0]) for r in conn.execute("SELECT rowid FROM tasks_fts WHERE tasks_fts MATCH ?", (expr,))}
    if comments:
        ids.update(
            int(r[0])
            for r in conn.execute(
                "SELECT c.task_id FROM comments_fts JOIN comments c ON c.id = comments_fts.rowid "
                "WHERE comments_fts MATCH ?",
                (expr,),
            )
        )
    return ids


def _ranks(conn: sqlite3.Connection, expr: str, *, comments: bool = True) -> dict[int, float]:
    """``bm25`` (lower is better) of every task the expression hits, best source wins."""
    out = {int(r[0]): float(r[1]) for r in conn.execute(
        "SELECT rowid, bm25(tasks_fts) FROM tasks_fts WHERE tasks_fts MATCH ?", (expr,))}
    if comments:
        for r in conn.execute(
            "SELECT c.task_id, bm25(comments_fts) FROM comments_fts JOIN comments c ON c.id = comments_fts.rowid "
            "WHERE comments_fts MATCH ?",
            (expr,),
        ):
            tid, rank = int(r[0]), float(r[1])
            if tid not in out or rank < out[tid]:
                out[tid] = rank
    return out


def _within(a: str, b: str, cap: int) -> int | None:
    """Edit distance between ``a`` and ``b`` (a swap of two neighbours counts one), or
    ``None`` when it exceeds ``cap``."""
    if abs(len(a) - len(b)) > cap:
        return None
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            best = min(best, v)
        if best > cap:
            return None
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= cap else None


def _vocab(conn: sqlite3.Connection) -> str:
    """The name of this connection's view over the words ``tasks_fts`` holds (term, doc count)."""
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.tasks_fts_vocab USING fts5vocab(main, tasks_fts, 'row')")
    return "temp.tasks_fts_vocab"


def _near_words(conn: sqlite3.Connection, term: str) -> list[str]:
    """Indexed words within the typo allowance of ``term`` (never ``term`` itself).

    The scan keeps only words sharing the term's first or last few letters:
    with one or two edits an end of the word is untouched, and filtering there
    keeps the edit-distance pass to a handful of words instead of the vocabulary.
    """
    word = _fold(term)
    cap = 2 if len(word) >= FUZZY_TWO_EDITS_LEN else 1
    anchor = cap + 1
    rows = conn.execute(
        f"SELECT term, doc FROM {_vocab(conn)} WHERE length(term) BETWEEN ? AND ? "
        "AND (substr(term, 1, ?) = ? OR substr(term, -?) = ?)",
        (len(word) - cap, len(word) + cap, anchor, word[:anchor], anchor, word[-anchor:]),
    ).fetchall()
    scored = []
    for r in rows:
        cand = str(r[0])
        if cand == word:
            continue
        dist = _within(word, cand, cap)
        if dist is not None:
            scored.append((dist, -int(r[1]), cand))
    scored.sort()
    return [cand for _, _, cand in scored[:FUZZY_WORDS_PER_TERM]]


def _fuzzy_eligible(term: str) -> bool:
    return len(term) >= FUZZY_MIN_LEN and term.isalpha()


def _fuzzy(
    conn: sqlite3.Connection, terms: list[str], exact_sets: list[set[int]], need: int, taken: set[int]
) -> tuple[dict[int, int], set[str]]:
    """Tasks the typo-tolerant pass adds, as ``{task id: terms matched}``, plus the near-words used.

    A task already in a stricter tier is never re-tiered; a new one needs a
    near-word hit for at least one term and, with the terms it matches exactly,
    at least ``need`` of them.
    """
    near_sets: dict[int, set[int]] = {}
    words: set[str] = set()
    for i, term in enumerate(terms):
        if not _fuzzy_eligible(term):
            continue
        near = _near_words(conn, term)
        if near:
            words.update(near)
            near_sets[i] = _task_ids(conn, " OR ".join(f'"{w}"' for w in near), comments=False)
    found: dict[int, int] = {}
    for tid in set().union(*near_sets.values()) if near_sets else ():
        if tid in taken:
            continue
        matched = {i for i, s in enumerate(exact_sets) if tid in s} | {i for i, s in near_sets.items() if tid in s}
        if len(matched) >= need:
            found[tid] = len(matched)
    return found, words


def _any_word(words: set[str] | list[str]) -> str:
    """An FTS5 expression for any of these indexed words, each as a whole word."""
    return " OR ".join(f'"{w}"' for w in sorted(words))


def _closest(conn: sqlite3.Connection, terms: list[str]) -> tuple[dict[int, float], set[str]]:
    """``({task id: likeness 0..1}, words that found them)`` for a query nothing else matched.

    The vocabulary is read once and each term is compared only with words of
    about its length; no task text is scanned.
    """
    by_length: dict[int, list[str]] = {}
    for r in conn.execute(f"SELECT term FROM {_vocab(conn)}"):
        by_length.setdefault(len(r[0]), []).append(r[0])
    per_term: list[dict[int, float]] = []
    used: set[str] = set()
    for term in terms:
        word = _fold(term)
        lengths = range(max(1, len(word) - CLOSEST_LENGTH_SLACK), len(word) + CLOSEST_LENGTH_SLACK + 1)
        pool = [w for n in lengths for w in by_length.get(n, ())]
        best: dict[int, float] = {}
        for near, likeness, _ in process.extract(word, pool, scorer=fuzz.ratio, limit=CLOSEST_WORDS):
            if likeness <= 0:  # not one letter in common
                continue
            used.add(near)
            for r in conn.execute(
                "SELECT rowid FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rowid DESC LIMIT ?",
                (f'"{near}"', CLOSEST_TASKS_PER_WORD),
            ):
                best[int(r[0])] = max(likeness / 100, best.get(int(r[0]), 0.0))
        per_term.append(best)
    scores = {
        tid: round(sum(b.get(tid, 0.0) for b in per_term) / len(terms), 3) for tid in set().union(*per_term)
    }
    return scores, used


def _pick_closest(conn: sqlite3.Connection, alike: list[int]) -> list[int]:
    """Of ``alike`` (most alike first), the ``CLOSEST_LIMIT`` to list: the best
    ``CLOSEST_OPEN`` open tasks, then the most alike of the rest, same order kept."""
    still_open = {int(r[0]) for r in conn.execute(f"SELECT id FROM tasks WHERE status NOT IN ({CLOSED_SQL})")}
    kept = set([tid for tid in alike if tid in still_open][:CLOSEST_OPEN])
    rest = [tid for tid in alike if tid not in kept][: CLOSEST_LIMIT - len(kept)]
    chosen = kept.union(rest)
    return [tid for tid in alike if tid in chosen]


_TOKENIZER = "tokenize='unicode61 remove_diacritics 2'"


def _details(conn: sqlite3.Connection, ids: list[int], expr: str) -> dict[int, dict[str, Any]]:
    """Source and snippet for each id: title, else description, else the best comment.

    The few hit documents are copied into a throwaway FTS5 table with the live
    index's tokenizer and the snippet is cut from that. Asking the live index
    for ``snippet()`` of chosen ids costs one full evaluation of the expression
    per id, which for a short prefix that expands to hundreds of words is
    seconds; over the copy it is a scan of a few dozen rows, and it reads the
    same tokens the live index does.

    The task text is free-form and may itself hold ``[`` (``[WIP] fix tap``), so
    "did the title match" is asked of a mark that cannot occur in text; the
    display ``[`` ``]`` are swapped in afterwards.
    """
    marks = ", ".join("?" * len(ids))
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS temp.hit_fts USING fts5(title, description, {_TOKENIZER})")
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS temp.hit_comments_fts USING fts5(body, {_TOKENIZER})")
    conn.execute("DELETE FROM temp.hit_fts")
    conn.execute("DELETE FROM temp.hit_comments_fts")
    conn.execute(
        f"INSERT INTO temp.hit_fts(rowid, title, description) SELECT id, title, description FROM tasks WHERE id IN ({marks})",
        ids,
    )
    conn.execute(
        f"INSERT INTO temp.hit_comments_fts(rowid, body) SELECT id, body FROM comments WHERE task_id IN ({marks})",
        ids,
    )
    out: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        """
        SELECT rowid AS id, snippet(hit_fts, 0, char(1), char(2), '…', 12) AS s_title,
               snippet(hit_fts, 1, char(1), char(2), '…', 12) AS s_desc,
               highlight(hit_fts, 0, char(1), char(2)) AS h_title,
               highlight(hit_fts, 1, char(1), char(2)) AS h_desc
          FROM temp.hit_fts WHERE hit_fts MATCH ?
        """,
        (expr,),
    ).fetchall():
        in_title = "" in (r["h_title"] or "")
        if not in_title and "" not in (r["h_desc"] or ""):
            continue
        snippet = (r["s_title"] if in_title else r["s_desc"]) or ""
        out[r["id"]] = {
            "matched_in": "title" if in_title else "description",
            "snippet": snippet.replace("", "[").replace("", "]"),
        }
    best: dict[int, tuple[float, str]] = {}
    for r in conn.execute(
        """
        SELECT c.task_id AS id, bm25(hit_comments_fts) AS rank,
               snippet(hit_comments_fts, 0, '[', ']', '…', 12) AS s_body
          FROM temp.hit_comments_fts JOIN comments c ON c.id = hit_comments_fts.rowid
         WHERE hit_comments_fts MATCH ?
        """,
        (expr,),
    ).fetchall():
        if r["id"] not in out and (r["id"] not in best or r["rank"] < best[r["id"]][0]):
            best[r["id"]] = (r["rank"], r["s_body"])
    for tid, (_, body) in best.items():
        out[tid] = {"matched_in": "comment", "snippet": body}
    return out


def rank_tasks(
    conn: sqlite3.Connection, q: str, *, limit: int = 50, exact_only: bool = False
) -> list[dict[str, Any]]:
    """Ranked hits, best first: ``{id, rank, matched_in, snippet, match_kind}``.

    ``exact_only`` stops after the ``exact`` tier — the filter boxes want "every
    word", not "something like it".
    """
    terms = split_terms(q)
    if not terms:
        return []
    exprs = [_term_expr(t) for t in terms]
    exact_sets = [_task_ids(conn, e) for e in exprs]
    covered = Counter(tid for s in exact_sets for tid in s)
    n = len(terms)
    need = (n + 1) // 2
    ranks = _ranks(conn, " OR ".join(exprs)) if covered else {}
    phrase_ids = _task_ids(conn, f'"{" ".join(terms)}"*') if n > 1 and covered else set()

    # (tier, not-the-whole-phrase, fewer terms matched or less alike, bm25, id) → match kind
    keyed: list[tuple[tuple[int, int, float, float, int], str]] = []
    for tid, k in covered.items():
        if k == n:
            keyed.append(((0, int(tid not in phrase_ids), 0, ranks.get(tid, 0.0), tid), MATCH_EXACT))
        elif n > 1 and k >= need and not exact_only:
            keyed.append(((1, 0, -k, ranks.get(tid, 0.0), tid), MATCH_PARTIAL))

    detail_expr = " OR ".join(exprs)
    if len(keyed) < limit and not exact_only:
        found, words = _fuzzy(conn, terms, exact_sets, need, {key[4] for key, _ in keyed})
        if found:
            fuzzy_ranks = _ranks(conn, _any_word(words), comments=False)
            keyed.extend(((2, 0, -k, fuzzy_ranks.get(tid, 0.0), tid), MATCH_SIMILAR) for tid, k in found.items())
            detail_expr += " OR " + _any_word(words)

    if not keyed and not exact_only:
        scores, words = _closest(conn, terms)
        if scores:
            detail_expr = _any_word(words)  # the typed terms found nothing: mark the words that did
            word_ranks = _ranks(conn, detail_expr, comments=False)
            alike = sorted(scores, key=lambda tid: (-scores[tid], word_ranks.get(tid, 0.0), tid))
            keyed = [((3, 0, -scores[tid], word_ranks.get(tid, 0.0), tid), MATCH_CLOSEST)
                     for tid in _pick_closest(conn, alike)]

    keyed.sort(key=lambda kv: kv[0])
    keyed = keyed[:limit]
    if not keyed:
        return []
    details = _details(conn, [key[4] for key, _ in keyed], detail_expr)
    out = []
    for key, kind in keyed:
        meta = details.get(key[4]) or {"matched_in": "title", "snippet": ""}
        out.append({"id": key[4], "rank": key[3], **meta, "match_kind": kind})
    return out
