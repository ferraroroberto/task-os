"""Voice enrichment (#147) — what the model may decide, and what it may not.

Nothing here touches the fleet's hub: every test points ``enrich.url`` at
:class:`tests.fixtures.chat_fake.FakeChat`, a loopback endpoint speaking the
chat-completions shape, so the request build, the ``urllib`` POST and the
answer parse are all the real ones. (The suite-wide config blanks
``enrich.url`` — see ``tests/conftest`` — so a test that forgets to point
somewhere gets "not reachable", never a live model.)

The theme running through most of it: **the model proposes words, the app
decides facts.** A title and a description are words, so the model owns them.
A due date is a fact about the calendar, and the model demonstrably gets it
wrong (a live probe answered `2026-09-13` for "before friday" when Friday was
the 11th), so it may only point at the phrase and :mod:`src.dates` resolves it.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.config import AppConfig, EnrichConfig
from src.enrich import (
    LLM,
    PARSER,
    EnrichClient,
    EnrichError,
    enrich_line,
    resolve_phrase,
    strip_wrappers,
)
from tests.fixtures.chat_fake import FakeChat

LOOPBACK = ("127.0.0.1", 12345)
#: A Monday. The live probe used this date, and "before friday" from here is
#: 2026-09-11 — the model answered 2026-09-13, a Sunday.
TODAY = date(2026, 9, 7)
NOTE = ("urgent, I need to call the plumber about the leaking radiator in the "
        "guest room before friday")


def config_for(url: str, model: str = "agentic_light_nothink") -> AppConfig:
    return AppConfig(enrich=EnrichConfig(url=url, model=model, timeout_seconds=5))


def _dead_url() -> str:
    with socket.socket() as s:          # a port nothing is listening on, right now
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/v1/chat/completions"


@pytest.fixture
def chat() -> Iterator[FakeChat]:
    with FakeChat() as fake:
        fake.says(title="Call the plumber about the guest-room radiator",
                  description="It is leaking.", due_phrase="before friday", starts_phrase=None)
        yield fake


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = dbmod.connect(tmp_path / "tasks.db")
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=LOOPBACK) as c:
        yield c


# ------------------------------------------------------------------- pieces


def test_the_json_is_found_inside_whatever_the_model_wrapped_it_in() -> None:
    """`response_format` is unusable on this backend (the model's template
    injects a `<think>` prefix the grammar cannot accommodate, probed live), so
    the wrappers are handled here instead of prevented upstream."""
    payload = '{"title": "Call the plumber"}'
    assert strip_wrappers(payload) == payload
    assert strip_wrappers(f"<think>weighing it up</think>\n{payload}") == payload
    assert strip_wrappers(f"```json\n{payload}\n```") == payload
    assert strip_wrappers(f"<think>hm</think>\n```\n{payload}\n```") == payload
    assert strip_wrappers(f"Here is the task:\n{payload}\nHope that helps.") == payload
    # Nothing JSON-shaped in it at all comes back as-is, for the caller to fail on.
    assert strip_wrappers("I could not do that") == "I could not do that"
    assert strip_wrappers("") == ""


def test_a_phrase_nobody_said_is_dropped() -> None:
    """The guard that matters. A model asked for "the words that say when"
    will cheerfully answer with a date it worked out instead, and a wrong day
    is worse than no day: nothing about it looks wrong later."""
    said, phrase = resolve_phrase("before friday", NOTE, TODAY)
    assert (said, phrase) == ("2026-09-11", "before friday")

    # …and Friday is the 11th, which is what the live model got wrong.
    assert date.fromisoformat(said).strftime("%A") == "Friday"

    for invented in ("next tuesday", "2026-09-13", "in 3 weeks"):
        assert resolve_phrase(invented, NOTE, TODAY) == (None, None), invented


def test_a_phrase_that_is_said_but_is_not_a_date_yields_no_date() -> None:
    """`src.dates` is the only thing allowed to turn words into a day, so a
    phrase it cannot read is simply not a date — never a guess."""
    assert resolve_phrase("the leaking radiator", NOTE, TODAY) == (None, None)
    # Case and trailing punctuation are the model's, not a difference of meaning.
    assert resolve_phrase("Before Friday.", NOTE, TODAY)[0] == "2026-09-11"
    for junk in (None, 42, "", "   ", {"date": "friday"}):
        assert resolve_phrase(junk, NOTE, TODAY) == (None, None), junk


# ------------------------------------------------------------------- client


def test_the_request_names_a_model_and_pins_today(chat: FakeChat) -> None:
    """The opposite of the transcription rule (#144), and worth pinning so the
    two are never confused: transcription names **no** model so the hub applies
    its audio role; there is no text role to defer to, so this one names it."""
    EnrichClient(config_for(chat.url)).fields(NOTE, today=TODAY)
    sent = chat.requests[-1]
    assert sent["model"] == "agentic_light_nothink"
    assert sent["temperature"] == 0
    system = sent["messages"][0]["content"]
    assert "2026-09-07" in system and "Monday" in system
    assert sent["messages"][1]["content"] == NOTE
    # No `response_format`: it is a 400 on this backend, not a nicety skipped.
    assert "response_format" not in sent


def test_only_the_keys_the_form_has_are_read(chat: FakeChat) -> None:
    chat.says(title="Call the plumber", description="", due_phrase=None,
              starts_phrase=None, priority="high", status="standby", assignee="me")
    got = EnrichClient(config_for(chat.url)).fields(NOTE, today=TODAY)
    assert set(got) == {"title", "description", "due_phrase", "starts_phrase"}


def test_every_way_the_answer_can_be_useless_is_one_error(chat: FakeChat) -> None:
    """One exception type, one place to catch it, one reason to record."""
    client = EnrichClient(config_for(chat.url))
    for content in ("I could not do that", "[1, 2, 3]", "", "{oops"):
        chat.content = content
        with pytest.raises(EnrichError):
            client.fields(NOTE, today=TODAY)

    chat.body = b"<html>502 Bad Gateway</html>"
    with pytest.raises(EnrichError):
        client.fields(NOTE, today=TODAY)
    chat.body = None

    chat.content = json.dumps({"title": "ok"})
    chat.status = 500
    with pytest.raises(EnrichError) as exc:
        client.fields(NOTE, today=TODAY)
    assert "500" in str(exc.value)


def test_an_unreachable_endpoint_says_so_rather_than_hanging_the_verdict() -> None:
    client = EnrichClient(config_for(_dead_url()))
    with pytest.raises(EnrichError) as exc:
        client.fields(NOTE, today=TODAY)
    assert "did not answer" in str(exc.value)
    # …and the cached "reachable" verdict is dropped, so the next probe re-asks
    # instead of reporting an endpoint that has just proved otherwise.
    assert client.probe()[0] is False


def test_an_unconfigured_install_is_a_state_not_a_failure() -> None:
    blank = EnrichClient(config_for(""))
    assert blank.status() == {"enabled": False, "reason": "no enrich.url in config",
                              "url": "", "model": "agentic_light_nothink", "checked_at": None}
    no_model = EnrichClient(config_for("http://127.0.0.1:8000/v1/chat/completions", model=""))
    assert no_model.status()["reason"] == "no enrich.model in config"


# -------------------------------------------------------------- enrich_line


def test_the_spoken_sentence_becomes_a_title_a_description_and_a_real_date(
    chat: FakeChat
) -> None:
    out = enrich_line(EnrichClient(config_for(chat.url)), NOTE, today=TODAY)
    assert out["source"] == LLM and out["model"] == "agentic_light_nothink"
    assert out["title"] == "Call the plumber about the guest-room radiator"
    assert out["description"] == "It is leaking."
    assert (out["due"], out["due_phrase"]) == ("2026-09-11", "before friday")
    assert out["starts"] is None
    assert out["reason"] is None
    # The whole point, against what the parser alone manages: it finds the
    # date (that is its job) and then leaves the entire remaining sentence as
    # the title, with nothing in the description — which is the thing a spoken
    # note most needs split.
    from src import quick_add
    bare = quick_add.parse(NOTE, TODAY)
    assert bare["due"] == "2026-09-11"
    assert bare["title"] == (
        "urgent, I need to call the plumber about the leaking radiator in the guest room"
    )


def test_no_date_spoken_means_no_date_filled(chat: FakeChat) -> None:
    """"Date only if you said one" — including when the model would rather
    fill it in. The phrase is not in the note, so it never becomes a day."""
    note = "call the plumber about the leaking radiator in the guest room"
    chat.says(title="Call the plumber", description="The guest-room radiator leaks.",
              due_phrase="next tuesday", starts_phrase="tomorrow")
    out = enrich_line(EnrichClient(config_for(chat.url)), note, today=TODAY)
    assert out["source"] == LLM
    assert (out["due"], out["due_phrase"]) == (None, None)
    assert (out["starts"], out["starts_phrase"]) == (None, None)


def test_a_resolved_iso_date_instead_of_a_phrase_is_discarded(chat: FakeChat) -> None:
    """This is what the live model actually did, and it did the arithmetic
    wrong. An ISO date is not in the note, so the guard catches it either way."""
    chat.says(title="Call the plumber", description="", due_phrase="2026-09-13",
              starts_phrase=None)
    out = enrich_line(EnrichClient(config_for(chat.url)), NOTE, today=TODAY)
    # The model's date is gone; what is left is the parser's own reading of
    # the note, which is the floor enrichment sits on top of. So the answer is
    # Friday the 11th — never the Sunday the model worked out.
    assert (out["due"], out["due_phrase"]) == ("2026-09-11", "before friday")

    # …and with nothing in the note for the parser to fall back to either, the
    # invented date leaves no trace at all.
    plain = "call the plumber about the radiator"
    none_left = enrich_line(EnrichClient(config_for(chat.url)), plain, today=TODAY)
    assert (none_left["due"], none_left["due_phrase"]) == (None, None)


def test_the_parser_is_the_floor_and_says_when_it_answered(chat: FakeChat) -> None:
    """Enrichment is a tidy-up on an answer that already exists. Losing it must
    never look like a broken microphone — and must never be silent about who
    answered."""
    line = "renew passport friday"
    parser_only = enrich_line(None, line, today=TODAY)
    assert parser_only["source"] == PARSER
    assert parser_only["title"] == "renew passport"
    assert parser_only["due"] == "2026-09-11"
    assert parser_only["reason"] == "enrichment service not started"

    down = enrich_line(EnrichClient(config_for(_dead_url())), line, today=TODAY)
    assert down["source"] == PARSER and down["due"] == "2026-09-11"
    assert "did not answer" in down["reason"]

    chat.content = "not json at all"
    junk = enrich_line(EnrichClient(config_for(chat.url)), line, today=TODAY)
    assert junk["source"] == PARSER and junk["title"] == "renew passport"
    assert "did not answer with JSON" in junk["reason"]

    # A model that answers with no title cannot be used either: the line has to
    # say something, and the parser's title already does.
    chat.says(title="", description="something", due_phrase=None, starts_phrase=None)
    titleless = enrich_line(EnrichClient(config_for(chat.url)), line, today=TODAY)
    assert titleless["source"] == PARSER and titleless["title"] == "renew passport"
    assert titleless["reason"] == "the model returned no title"


def test_the_parent_reference_stays_the_parsers(chat: FakeChat) -> None:
    """``#12`` and ``› garden-bot`` are syntax, not language — the model was
    never asked about them, so it cannot lose them."""
    chat.says(title="Order the sensor", description="", due_phrase=None, starts_phrase=None)
    out = enrich_line(EnrichClient(config_for(chat.url)), "order sensor #12", today=TODAY)
    assert out["source"] == LLM and out["parent_ref"] == {"id": 12}


# --------------------------------------------------------------------- route


def _point_at(client: TestClient, url: str) -> None:
    client.app.state.enrich = EnrichClient(config_for(url))


def test_the_route_answers_200_however_badly_it_went(
    client: TestClient, chat: FakeChat
) -> None:
    """There is nothing for a client to recover from: the transcript is already
    on the line. So the failure is *reported*, not raised."""
    _point_at(client, chat.url)
    ok = client.post("/api/enrich", json={"text": NOTE, "today": "2026-09-07"})
    assert ok.status_code == 200
    assert ok.json()["source"] == LLM and ok.json()["due"] == "2026-09-11"

    _point_at(client, _dead_url())
    down = client.post("/api/enrich", json={"text": NOTE, "today": "2026-09-07"})
    assert down.status_code == 200
    body = down.json()
    assert body["source"] == PARSER and body["reason"]
    assert body["title"], "the parser's answer still has to be there"


def test_the_route_resolves_the_parent_like_parse_does(
    client: TestClient, chat: FakeChat
) -> None:
    _point_at(client, chat.url)
    made = client.post("/api/tasks", json={"title": "garden-bot"}).json()
    chat.says(title="Order the sensor", description="", due_phrase=None, starts_phrase=None)
    out = client.post("/api/enrich", json={"text": "order sensor › garden-bot"}).json()
    assert out["parent"] == {"id": made["id"], "title": "garden-bot"}


def test_a_bad_today_is_the_one_thing_the_route_refuses(client: TestClient) -> None:
    """It is the caller's own mistake, not the model's — and answering 200 with
    a silently different reference date would be worse than saying so."""
    res = client.post("/api/enrich", json={"text": NOTE, "today": "friday"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"


def test_enrich_is_gated_like_every_other_api_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New `/api/` routes are closed by construction (`src/auth.py`), and a
    route that sends text to a model is exactly one to prove it for."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 1)) as outside:
        res = outside.post("/api/enrich", json={"text": NOTE})
        assert res.status_code == 401


def test_status_reports_enrichment_over_http(client: TestClient, chat: FakeChat) -> None:
    _point_at(client, chat.url)
    st = client.get("/api/status").json()["enrich"]
    assert st["enabled"] is True and st["url"] == chat.url
    assert st["model"] == "agentic_light_nothink"
