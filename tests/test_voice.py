"""Voice quick-add (#92) — the probe, the forward, and the route around them.

Nothing here touches the fleet's real hub or whisper server: every test points
``voice.transcribe_url`` (and, where the fallback matters,
``voice.fallback_url``) at :class:`tests.fixtures.whisper_fake.FakeWhisper`, a
loopback endpoint that speaks the same shapes, so the multipart build, the
``urllib`` POST and the response parse are all the real ones. (The suite-wide
config blanks both endpoints — see ``tests/conftest`` — so a test that forgets
to point somewhere gets "not reachable", never the live model.)
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src import voice as voicemod
from src.config import AppConfig, VoiceConfig
from src.voice import VoiceClient, VoiceError, build_multipart, clean_transcript, endpoint_of
from tests.fixtures.whisper_fake import FakeWhisper, parse_multipart

LOOPBACK = ("127.0.0.1", 12345)


def wav_bytes(samples: int = 8000, rate: int = 16000) -> bytes:
    """A silent 16 kHz mono PCM WAV — what ``static/voice.js`` uploads."""
    data = b"\x00\x00" * samples
    return (
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )


def config_for(url: str, fallback: str = "") -> AppConfig:
    return AppConfig(voice=VoiceConfig(transcribe_url=url, fallback_url=fallback))


@pytest.fixture
def whisper() -> Iterator[FakeWhisper]:
    with FakeWhisper(text="buy a new filter for the dehumidifier next week") as fake:
        yield fake


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over its own database — the route needs one for the parse."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=LOOPBACK) as c:
        yield c


# ------------------------------------------------------------------- pieces


def test_endpoint_of_takes_only_addressable_http_urls() -> None:
    assert endpoint_of("http://127.0.0.1:8090/v1/audio/transcriptions") == ("127.0.0.1", 8090)
    assert endpoint_of("https://box.example/v1/audio/transcriptions") == ("box.example", 443)
    assert endpoint_of("http://box.example/x") == ("box.example", 80)
    for bad in ("", "not a url", "file:///tmp/x.wav", "ws://127.0.0.1:8090", "http:///v1"):
        assert endpoint_of(bad) is None, bad


def test_multipart_carries_the_file_and_the_scalars_it_was_given() -> None:
    audio = wav_bytes(16)
    body, header = build_multipart(
        audio, filename="clip.wav", content_type="audio/wav",
        fields={"response_format": "json"},
    )
    parsed = parse_multipart(body, header)
    assert parsed["filename"] == "clip.wav"
    assert parsed["file_content_type"] == "audio/wav"
    assert parsed["file"] == audio          # byte-for-byte, no re-encoding here
    assert parsed["fields"] == {"response_format": "json"}


def test_the_answer_is_read_as_json_or_as_plain_text() -> None:
    """whisper-server answers JSON with ``response_format=json`` and bare text
    otherwise; a transcript must not depend on which was negotiated."""
    assert voicemod._text_of(b'{"text": " hello there\\n"}') == "hello there"
    assert voicemod._text_of(b" hello there\n") == "hello there"
    assert voicemod._text_of(b'{"error": "nope"}') == ""


def test_a_dictated_line_keeps_its_date_despite_whisper_s_full_stop() -> None:
    """The live :8090 answers "Buy a new filter … next week." — with the stop,
    ``next week.`` is not a date phrase and the spoken due silently vanishes.
    Trailing punctuation is the transcription's, not the speaker's."""
    from datetime import date

    from src.quick_add import parse

    heard = " Buy a new filter for the dehumidifier next week.\n"
    assert clean_transcript(heard) == "Buy a new filter for the dehumidifier next week"
    parsed = parse(clean_transcript(heard), date(2026, 9, 7))
    assert parsed["due"] == "2026-09-14" and parsed["title"] == "Buy a new filter for the dehumidifier"
    # …and the raw transcript is exactly what would have lost it
    assert parse(heard.strip(), date(2026, 9, 7))["due"] is None

    assert clean_transcript("nothing here...") == "nothing here"
    assert clean_transcript("Call mum!") == "Call mum"
    assert clean_transcript("a, b, c") == "a, b, c"      # only the tail is touched
    assert clean_transcript("?") == "?"                  # punctuation alone is the title
    assert clean_transcript("") == ""


# -------------------------------------------------------------------- probe


def test_unconfigured_reasons_are_distinct_because_the_fix_is() -> None:
    assert VoiceClient(config_for("")).unconfigured_reason == "no voice.transcribe_url in config"
    assert "not an http(s) URL" in VoiceClient(config_for("八")).unconfigured_reason
    assert VoiceClient(config_for("http://127.0.0.1:1/x")).unconfigured_reason is None


def test_status_is_reachable_when_something_answers_the_port(whisper: FakeWhisper) -> None:
    st = VoiceClient(config_for(whisper.url)).status()
    assert st["enabled"] is True and st["reason"] is None
    assert st["url"] == whisper.url and st["checked_at"]


def test_status_off_always_carries_the_reason() -> None:
    with socket.socket() as s:      # a port nothing is listening on, right now
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    st = VoiceClient(config_for(f"http://127.0.0.1:{dead}/v1/audio/transcriptions")).status()
    assert st["enabled"] is False
    # Refused or timed out depending on how fast this OS reports a dead port
    # (Windows takes ~2 s); either way the reason names the endpoint and says
    # it is not answering.
    assert f"127.0.0.1:{dead}" in st["reason"]

    blank = VoiceClient(config_for("")).status()
    assert blank == {"enabled": False, "reason": "no voice.transcribe_url in config",
                     "url": "", "serving": None, "partial_interval_seconds": 1.5,
                     "checked_at": None}


def test_a_timed_out_probe_does_not_claim_to_know_which_failure_it_was(
    monkeypatch: pytest.MonkeyPatch, whisper: FakeWhisper
) -> None:
    """A connect that never came back has not established *why* — the server
    may be down, or port 8090 may be held by the fleet's other transcriber.
    The reason names both instead of asserting one."""
    def _hang(*_a: object, **_kw: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", _hang)
    st = VoiceClient(config_for(whisper.url)).status()
    assert st["enabled"] is False
    assert "did not answer within" in st["reason"]
    assert "may be down" in st["reason"] and "may be busy" in st["reason"]


def test_the_probe_is_cached_so_a_shared_port_is_not_hammered(whisper: FakeWhisper) -> None:
    """:8090 is mutex-shared with automation/audio/transcribe_voice, and the
    mic asks on every dialog open — the verdict has to be reused."""
    client = VoiceClient(config_for(whisper.url))
    assert client.probe()[0] is True
    whisper.stop()                                  # the server goes away…
    assert client.probe()[0] is True                # …and the cached verdict holds
    assert client.probe(force=True)[0] is False     # …until it is actually re-asked


# --------------------------------------------------------------- transcribe


def test_transcribe_posts_the_clip_and_returns_what_was_heard(whisper: FakeWhisper) -> None:
    audio = wav_bytes()
    text = VoiceClient(config_for(whisper.url)).transcribe(audio)
    assert text == "buy a new filter for the dehumidifier next week"
    sent = whisper.requests[-1]
    assert sent["path"] == "/v1/audio/transcriptions"
    assert sent["file"] == audio and sent["filename"] == "clip.wav"
    assert sent["fields"]["response_format"] == "json"


def test_a_refusal_and_a_silence_are_different_errors(whisper: FakeWhisper) -> None:
    """The fix differs: a 400 means the body was wrong, an unanswered port
    means whisper is not up. Collapsing them would hide both."""
    client = VoiceClient(config_for(whisper.url))
    # whisper.cpp's own answer to a format it cannot decode — verified against
    # the live :8090 on 2026-09-07: 200 for WAV, 400 "Invalid request" for
    # webm/opus and mp4/aac alike.
    whisper.status, whisper.body = 400, b"Invalid request"
    with pytest.raises(VoiceError) as refused:
        client.transcribe(wav_bytes(), content_type="audio/webm")
    assert refused.value.http_status == 502 and refused.value.code == "voice_rejected"
    assert "Invalid request" in refused.value.detail and "audio/webm" in refused.value.detail

    whisper.stop()
    with pytest.raises(VoiceError) as silent:
        client.transcribe(wav_bytes())
    assert silent.value.http_status == 503 and silent.value.code == "voice_unavailable"


def test_a_failed_post_drops_the_cached_verdict(whisper: FakeWhisper) -> None:
    """Otherwise the mic keeps saying "on" for 15 s after whisper died."""
    client = VoiceClient(config_for(whisper.url))
    assert client.probe()[0] is True
    whisper.stop()
    with pytest.raises(VoiceError):
        client.transcribe(wav_bytes())
    assert client.probe()[0] is False       # not the cached True


def test_transcribe_refuses_an_empty_or_oversized_body(whisper: FakeWhisper) -> None:
    client = VoiceClient(config_for(whisper.url))
    with pytest.raises(VoiceError) as empty:
        client.transcribe(b"")
    assert empty.value.http_status == 422
    with pytest.raises(VoiceError) as big:
        client.transcribe(b"\x00" * (voicemod.MAX_AUDIO_BYTES + 1))
    assert big.value.http_status == 413
    assert not whisper.requests           # neither one reached the endpoint


def test_transcribe_says_voice_is_off_rather_than_posting_nowhere() -> None:
    with pytest.raises(VoiceError) as exc:
        VoiceClient(config_for("")).transcribe(wav_bytes())
    assert exc.value.http_status == 409 and exc.value.code == "voice_disabled"


# -------------------------------------------------------------------- route


def _point_at(client: TestClient, url: str) -> None:
    client.app.state.voice = VoiceClient(config_for(url))


def test_transcribe_route_returns_the_text_and_its_quick_add_parse(
    client: TestClient, whisper: FakeWhisper
) -> None:
    """One round trip, not two: the transcript's whole point is to become the
    quick-add line, and the phone pays for every extra hop."""
    _point_at(client, whisper.url)
    res = client.post("/api/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "buy a new filter for the dehumidifier next week"
    # …and it is the same split POST /api/parse would have given that line.
    parsed = client.post("/api/parse", json={"text": body["text"]}).json()
    assert body["parse"]["title"] == parsed["title"] == "buy a new filter for the dehumidifier"
    assert body["parse"]["due"] == parsed["due"] and body["parse"]["due"] is not None
    assert whisper.requests[-1]["file_content_type"] == "audio/wav"


def test_transcribe_route_maps_each_failure_to_its_own_status(
    client: TestClient, whisper: FakeWhisper
) -> None:
    _point_at(client, "")
    off = client.post("/api/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert off.status_code == 409 and off.json()["error"]["code"] == "voice_disabled"

    _point_at(client, whisper.url)
    empty = client.post("/api/transcribe", content=b"", headers={"Content-Type": "audio/wav"})
    assert empty.status_code == 422

    whisper.status, whisper.body = 400, b"Invalid request"
    bad = client.post("/api/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert bad.status_code == 502
    assert "Invalid request" in bad.json()["error"]["detail"]


def test_an_oversized_upload_is_refused_before_it_is_read(
    client: TestClient, whisper: FakeWhisper
) -> None:
    """The Content-Length claim is checked first so a huge body never lands in
    memory; the real length is checked again after, because a claim is not a
    fact."""
    _point_at(client, whisper.url)
    res = client.post(
        "/api/transcribe", content=b"\x00" * 32,
        headers={"Content-Type": "audio/wav", "Content-Length": str(voicemod.MAX_AUDIO_BYTES + 1)},
    )
    assert res.status_code == 413 and res.json()["error"]["code"] == "audio_too_large"
    assert not whisper.requests


def test_status_carries_the_voice_state(client: TestClient, whisper: FakeWhisper) -> None:
    """The mic button, the Settings card and ``tasks status`` read one call."""
    _point_at(client, whisper.url)
    on = client.get("/api/status").json()["voice"]
    assert on["enabled"] is True and on["reason"] is None and on["url"] == whisper.url

    _point_at(client, "")
    off = client.get("/api/status").json()["voice"]
    assert off["enabled"] is False and off["reason"] == "no voice.transcribe_url in config"


def test_transcribe_is_gated_like_every_other_api_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """New /api/ routes are closed by construction (CLAUDE.md) — a non-loopback
    client with no token must not be able to post audio into this house."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 1)) as outside:
        res = outside.post("/api/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert res.status_code == 401 and res.json()["error"]["code"] == "unauthorized"


# ------------------------------------------------------- hub-first routing


def _dead_url() -> str:
    """A URL whose port nothing is listening on, right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/v1/audio/transcriptions"


def test_the_hub_is_asked_first_and_no_model_is_named(whisper: FakeWhisper) -> None:
    """Naming no model is what makes the hub apply its transcribe *role* —
    parakeet ahead of whisper — rather than a concrete engine (#144)."""
    with FakeWhisper(text="from the fallback") as local:
        client = VoiceClient(config_for(whisper.url, local.url))
        assert client.transcribe(wav_bytes()) == "buy a new filter for the dehumidifier next week"
        assert not local.requests                       # the fallback was never asked
    assert "model" not in whisper.requests[-1]["fields"]
    assert whisper.requests[-1]["fields"] == {"response_format": "json"}


def test_an_unreachable_hub_falls_back_to_the_local_whisper_server() -> None:
    with FakeWhisper(text="from the fallback") as local:
        client = VoiceClient(config_for(_dead_url(), local.url))
        assert client.transcribe(wav_bytes()) == "from the fallback"
        assert len(local.requests) == 1
        st = client.status()
        assert st["enabled"] is True and st["serving"] == "fallback" and st["url"] == local.url


def test_a_hub_that_answers_and_refuses_is_never_second_guessed(whisper: FakeWhisper) -> None:
    """The rule voice-transcriber sets: only a *transport* failure earns a
    second endpoint. An endpoint that answered has told us something, and
    quietly substituting another engine's opinion would hide it."""
    with FakeWhisper(text="from the fallback") as local:
        whisper.status, whisper.body = 400, b"audio conversion failed"
        client = VoiceClient(config_for(whisper.url, local.url))
        with pytest.raises(VoiceError) as exc:
            client.transcribe(wav_bytes())
        assert exc.value.http_status == 502 and exc.value.code == "voice_rejected"
        assert "audio conversion failed" in exc.value.detail
        assert not local.requests                       # never asked


def test_both_endpoints_down_names_both() -> None:
    client = VoiceClient(config_for(_dead_url(), _dead_url()))
    with pytest.raises(VoiceError) as exc:
        client.transcribe(wav_bytes())
    assert exc.value.http_status == 503 and exc.value.code == "voice_unavailable"
    assert "the hub" in exc.value.detail and "the local whisper server" in exc.value.detail

    st = client.status()
    assert st["enabled"] is False and st["serving"] is None
    assert "the hub" in st["reason"] and "the local whisper server" in st["reason"]


def test_a_blank_fallback_is_simply_no_second_chance(whisper: FakeWhisper) -> None:
    client = VoiceClient(config_for(whisper.url, ""))
    assert [name for name, _ in client.targets()] == ["hub"]
    assert client.status()["serving"] == "hub"


def test_status_names_which_endpoint_is_serving_over_http(
    client: TestClient, whisper: FakeWhisper
) -> None:
    """Settings and the CLI both render this — "parakeet, or the local CPU
    whisper?" has to be answerable without reading a log."""
    client.app.state.voice = VoiceClient(config_for(whisper.url))
    on = client.get("/api/status").json()["voice"]
    assert on["enabled"] is True and on["serving"] == "hub" and on["url"] == whisper.url


# ------------------------------------------------------- the live transcript


def test_a_partial_asks_for_the_words_and_nothing_else(
    client: TestClient, whisper: FakeWhisper
) -> None:
    """``?parse=0`` is what the rolling pass uses while you are still speaking.

    It must return the transcript alone: parsing a fragment would put a due
    date on screen that moves as the sentence lands, and it would run
    ``resolve_parent`` — a database query — once a second for an answer nobody
    is shown.
    """
    _point_at(client, whisper.url)
    res = client.post(
        "/api/transcribe?parse=0", content=wav_bytes(), headers={"Content-Type": "audio/wav"},
    )
    assert res.status_code == 200
    assert res.json() == {"text": "buy a new filter for the dehumidifier next week"}

    # …and the default is unchanged: a request that says nothing still parses.
    full = client.post("/api/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert "parse" in full.json()


def test_a_partial_reports_a_failure_the_same_way_the_final_pass_does(
    client: TestClient
) -> None:
    """The client drops a failed partial silently, but the route must not
    invent a success for it — the same code and envelope either way."""
    _point_at(client, _dead_url())
    res = client.post(
        "/api/transcribe?parse=0", content=wav_bytes(), headers={"Content-Type": "audio/wav"},
    )
    assert res.status_code == 503 and res.json()["error"]["code"] == "voice_unavailable"


def test_the_live_cadence_is_the_installs_number_not_the_pages(
    client: TestClient, whisper: FakeWhisper
) -> None:
    """``static/voice.js`` reads the interval off ``/api/status`` instead of
    hardcoding one, so the cadence is a single install-level fact."""
    client.app.state.voice = VoiceClient(config_for(whisper.url))
    assert client.get("/api/status").json()["voice"]["partial_interval_seconds"] == 1.5


def test_a_zero_interval_turns_the_live_transcript_off_without_turning_voice_off(
    whisper: FakeWhisper
) -> None:
    """``0`` is the documented way to go back to one transcription on stop.
    It must not read as "voice is broken" anywhere."""
    cfg = AppConfig(voice=VoiceConfig(transcribe_url=whisper.url, partial_interval_seconds=0))
    st = VoiceClient(cfg).status()
    assert st["partial_interval_seconds"] == 0 and st["enabled"] is True


def test_an_unusable_interval_in_the_config_falls_back_loudly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A typo must not silently become "live transcript off" — that would read
    as a deliberate setting rather than a broken one."""
    from src.config import load_config
    from tests.conftest import write_test_config

    for bad in ("soon", -1):
        cfg_path = write_test_config(tmp_path / f"cfg-{bad}.json", partial_interval_seconds=bad)
        with caplog.at_level("WARNING"):
            caplog.clear()
            cfg = load_config(cfg_path)
        assert cfg.voice.partial_interval_seconds == 1.5, bad
        assert any("partial_interval_seconds" in r.getMessage() for r in caplog.records), bad

    good = write_test_config(tmp_path / "cfg-ok.json", partial_interval_seconds=0.75)
    assert load_config(good).voice.partial_interval_seconds == 0.75
