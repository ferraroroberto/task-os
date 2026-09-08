"""The folder ranking (#158) as a pure function — prompt, validator, degrade.

``src/archive_rank.py`` touches no database, no Outlook and no hub of its own:
it takes mails, corrections and a client, and returns picks. So everything the
model is allowed to do — and everything it is refused — is provable here with a
canned client, and the service tests (``tests/test_archive.py``) only have to
prove the wiring.

Synthetic throughout, as everything in this repo's fixtures is: the subjects,
senders and folders are invented.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.ai.client import AIError
from src.archive_rank import Pick, build_prompt, format_correction, rank, short_folder
from tests.fixtures.archiver_fake import FOLDER_BILLS, FOLDER_HOUSE, candidate, mail


class FakeHub:
    """A canned hub: hands back the next answer and records every prompt."""

    model = "fake_model"

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        self.prompts.append(user)
        self.systems.append(system)
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def picks_doc(*picks: dict[str, Any]) -> dict[str, Any]:
    return {"picks": list(picks)}


def pick_for(message_id: str, candidate_index: int | None, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "message_id": message_id, "candidate": candidate_index,
        "confidence": confidence, "reason": "the thread continues here",
    }


def two_mails() -> list[dict[str, Any]]:
    return [
        mail("a@example.invalid", subject="Boiler service",
             candidates=[candidate(FOLDER_HOUSE, 0.9), candidate(FOLDER_BILLS, 0.4)]),
        mail("b@example.invalid", subject="Water bill",
             candidates=[candidate(FOLDER_HOUSE, 0.6), candidate(FOLDER_BILLS, 0.5)]),
    ]


# ------------------------------------------------------------------- prompt


def test_the_prompt_carries_indexed_candidates_and_the_corrections() -> None:
    """The model chooses an index; it is never shown a place to type a path."""
    hub = FakeHub(picks_doc(pick_for("a@example.invalid", 0), pick_for("b@example.invalid", 1)))
    corrections = [{
        "subject": "An older bill", "sender": "billing@example.invalid",
        "suggested_folder": FOLDER_HOUSE, "chosen_folder": FOLDER_BILLS,
        "hint": "bills from this sender go to admin",
    }]
    rank(two_mails(), corrections, hub)

    payload = json.loads(hub.prompts[0])
    assert [c["index"] for c in payload["mails"][0]["candidates"]] == [0, 1]
    assert payload["mails"][0]["candidates"][0]["folder"] == "archive/house/heating"
    assert payload["corrections"] == [
        'mail "An older bill" from billing@example.invalid → suggested archive/house/heating, '
        "chosen archive/admin/bills, hint: bills from this sender go to admin"
    ]
    # The system prompt is the whole contract with an open-weight model: JSON
    # only, an index only, and never a date.
    assert "candidate is the index" in hub.systems[0]
    assert "never propose a date" in hub.systems[0]


def test_a_correction_without_a_hint_still_reads_as_an_example() -> None:
    line = format_correction({
        "subject": "Roof quote", "sender": "someone@example.invalid",
        "suggested_folder": "", "chosen_folder": FOLDER_HOUSE,
    })
    assert line.endswith("suggested nothing, chosen archive/house/heating")
    assert short_folder("E:\\a\\b\\c\\d\\e") == "c/d/e"


def test_only_the_head_of_the_archivers_list_is_shown_and_accepted() -> None:
    """The tail of a ten-deep ranking is noise the model would have to read.

    And the cut is one rule, not two: an index the prompt never offered is
    refused by the validator, so trimming can never widen what a model may pick.
    """
    deep = mail("deep@example.invalid", candidates=[
        candidate(f"E:\\archive\\f{n}", 0.9 - n / 100) for n in range(10)
    ])
    hub = FakeHub(
        picks_doc(pick_for("deep@example.invalid", 7)),
        picks_doc(pick_for("deep@example.invalid", 5)),
    )
    refused = rank([deep], [], hub)
    assert refused.ranked == 0
    assert "outside its 6 candidates" in refused.errors[0]
    assert len(json.loads(hub.prompts[0])["mails"][0]["candidates"]) == 6

    accepted = rank([deep], [], hub)
    assert accepted.picks["deep@example.invalid"].candidate == 5


def test_long_fields_are_bounded_before_they_reach_the_hub() -> None:
    """A mail with a novel in its preview must not blow one batch's prompt up."""
    big = mail(
        "big@example.invalid", subject="S" * 400, sender="x" * 400,
        candidates=[candidate(FOLDER_HOUSE, 0.9)],
    )
    big["body_preview"] = "P" * 4000
    hub = FakeHub(picks_doc(pick_for("big@example.invalid", 0)))
    rank([big], [], hub)
    context = json.loads(hub.prompts[0])["mails"][0]
    assert len(context["subject"]) == 160 and len(context["from"]) == 120
    assert len(context["preview"]) == 400


# ---------------------------------------------------------------- the picks


def test_the_picks_come_back_keyed_by_mail_with_the_agreement() -> None:
    hub = FakeHub(picks_doc(
        pick_for("a@example.invalid", 0, 0.95), pick_for("b@example.invalid", 1, 0.71),
    ))
    ranking = rank(two_mails(), [], hub)

    assert ranking.picks["a@example.invalid"] == Pick(0, 0.95, "the thread continues here", "model")
    assert ranking.picks["b@example.invalid"].candidate == 1
    assert ranking.errors == []
    # One of the two went where the archiver would have put it.
    assert (ranking.ranked, ranking.agreed) == (2, 1)
    assert ranking.agreement == pytest.approx(0.5)


def test_nothing_to_rank_is_not_an_agreement_of_zero() -> None:
    """``None`` says the model ranked nothing; 0.0 would say it disagreed with everything."""
    hub = FakeHub(picks_doc())
    unrankable = [
        mail("none@example.invalid", candidates=[]),
        mail("filed@example.invalid", already_archived="E:\\archive\\x.msg",
             candidates=[candidate(FOLDER_HOUSE, 0.9)]),
    ]
    ranking = rank(unrankable, [], hub)
    assert ranking.picks == {} and ranking.agreement is None
    assert hub.prompts == []  # neither mail was ever sent


def test_mails_are_split_into_batches_of_the_configured_size() -> None:
    mails = [
        mail(f"m{n}@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])
        for n in range(5)
    ]
    hub = FakeHub(
        picks_doc(*(pick_for(f"m{n}@example.invalid", 0) for n in range(2))),
        picks_doc(*(pick_for(f"m{n}@example.invalid", 0) for n in range(2, 4))),
        picks_doc(pick_for("m4@example.invalid", 0)),
    )
    ranking = rank(mails, [], hub, batch_size=2)
    assert len(hub.prompts) == 3 and ranking.ranked == 5


# --------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("answer", "detail"),
    [
        ("not json at all", "invalid JSON"),
        ({"suggestions": []}, "exactly the picks key"),
        ({"picks": "nope"}, "picks is not a list"),
        (picks_doc({"message_id": "a@example.invalid", "candidate": 0}), "documented keys"),
        (picks_doc(pick_for("a@example.invalid", 0)), "do not cover exactly"),
        (
            picks_doc(pick_for("a@example.invalid", 0), pick_for("ghost@example.invalid", 0)),
            "not in this batch",
        ),
        (
            picks_doc(pick_for("a@example.invalid", 7), pick_for("b@example.invalid", 0)),
            "outside its 2 candidates",
        ),
        (
            picks_doc(pick_for("a@example.invalid", 0, 4.0), pick_for("b@example.invalid", 0)),
            "outside 0..1",
        ),
        (
            picks_doc(
                {**pick_for("a@example.invalid", 0), "confidence": "high"},
                pick_for("b@example.invalid", 0),
            ),
            "not a number",
        ),
        (
            picks_doc(
                {**pick_for("a@example.invalid", 0), "reason": "  "},
                pick_for("b@example.invalid", 0),
            ),
            "missing reason",
        ),
        (
            picks_doc(pick_for("a@example.invalid", 0), pick_for("a@example.invalid", 1)),
            "two picks for the same mail",
        ),
    ],
)
def test_an_unusable_answer_degrades_the_whole_batch_loudly(answer: Any, detail: str) -> None:
    """Every mail in the batch falls back — and the run is told which failure it was.

    A partially-trusted answer is the one outcome that must not exist: an
    out-of-range index or a missing id means the model was not answering about
    these mails, so nothing in that batch is the model's decision.
    """
    hub = FakeHub(answer)
    ranking = rank(two_mails(), [], hub)

    assert ranking.ranked == 0 and ranking.agreement is None
    assert len(ranking.errors) == 1
    assert "ai_invalid_response" in ranking.errors[0] and detail in ranking.errors[0]
    for message_id in ("a@example.invalid", "b@example.invalid"):
        fallback = ranking.picks[message_id]
        assert fallback == Pick(
            None, None,
            "the local model could not rank this batch (ai_invalid_response) — the archiver's "
            "own ranking was used",
            "fallback",
        )


def test_a_hub_outage_degrades_that_batch_and_leaves_the_others_alone() -> None:
    """One dead batch is not a dead run — the other still carries the model's picks."""
    mails = [
        mail(f"m{n}@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)])
        for n in range(4)
    ]
    hub = FakeHub(
        AIError("ai_unavailable", "local AI hub unavailable", http_status=503),
        picks_doc(*(pick_for(f"m{n}@example.invalid", 0) for n in (2, 3))),
    )
    ranking = rank(mails, [], hub, batch_size=2)

    assert [p.source for p in ranking.picks.values()] == ["fallback", "fallback", "model", "model"]
    assert ranking.ranked == 2 and ranking.agreement == pytest.approx(1.0)
    assert "ai_unavailable" in ranking.errors[0]


def test_a_fenced_answer_is_still_read() -> None:
    """Open-weight models like a code fence; that is not a malformed answer."""
    body = json.dumps(picks_doc(pick_for("a@example.invalid", 1), pick_for("b@example.invalid", 0)))
    hub = FakeHub(f"Here you go:\n```json\n{body}\n```")
    ranking = rank(two_mails(), [], hub)
    assert ranking.picks["a@example.invalid"].candidate == 1


def test_the_prompt_is_small_enough_for_a_full_batch() -> None:
    """Eight mails with twenty examples must stay well under the model's context.

    The live measurement is in the PR; this is the guard that keeps it true —
    the bound that actually bites is the per-field truncation above.
    """
    mails = [
        mail(f"m{n}@example.invalid", subject=f"A synthetic subject {n}" * 4,
             candidates=[candidate(FOLDER_HOUSE, 0.9), candidate(FOLDER_BILLS, 0.5)])
        for n in range(8)
    ]
    corrections = [{
        "subject": f"An older thread {n}", "sender": "someone@example.invalid",
        "suggested_folder": FOLDER_HOUSE, "chosen_folder": FOLDER_BILLS,
        "hint": "this sender always goes here",
    } for n in range(20)]
    prompt = build_prompt(mails, corrections)
    assert len(prompt) < 24_000  # ~6k tokens, the ceiling the issue set
