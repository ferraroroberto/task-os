"""Story 22 — say the task instead of typing it (issues #92, #144, #146).

    Open the add dialog, click the mic. It turns red and becomes a stop
    square, and the words appear on the line *while you speak*. Click again
    and the line settles: the transcript, with next week's date already in the
    Due field, one Enter from being a task. Same gesture on the phone, over the
    one HTTPS endpoint it already has. An install with no transcription
    endpoint says so on the button and in Settings, and the mic never pretends
    it can record.

**Nothing real is recorded and nothing real is transcribed, but everything
between them is the shipped code.** Two things are stood in for:

  * the transcription endpoint — ``tests/fixtures/whisper_fake.FakeWhisper``,
    a loopback server speaking the OpenAI audio shape the hub and
    whisper-server share. The suite must never depend on the fleet's hub
    (``:8000``) or whisper server (``:8090``) being up — ``tests/conftest``
    blanks both ``voice`` endpoints for exactly that reason;
  * the microphone — an init script hands ``getUserMedia`` a **real**
    ``MediaStream``, synthesised by Web Audio from a tone. Real is the point:
    ``static/voice.js`` taps the stream through an AudioWorklet, so a faked
    stream object would test nothing.

Everything else runs for real: the toggle, the worklet capture, the rolling
partial passes, the 16 kHz mono WAV encode, the ``POST /api/transcribe`` body
(with and without ``?parse=0``), the server-side multipart forward, the
quick-add parse that rides back with the final text, the chips, and the create.
That is deliberately *more* than the issue asked for — the route is the half
most likely to break.

    docs/screenshots/story-22-voice-1-desktop.png   the add dialog, mic ready
    docs/screenshots/story-22-voice-2-desktop.png   recording: red stop square,
                                                    the partial already on the line
    docs/screenshots/story-22-voice-3-desktop.png   stopped: the transcript + its parsed due
    docs/screenshots/story-22-voice-4-desktop.png   the spoken task in To Do (dark)
    docs/screenshots/story-22-voice-5-phone.png     the same gesture on the phone
    docs/screenshots/story-22-voice-6-desktop.png   no endpoint: the reason on the button
    docs/screenshots/story-22-voice-7-desktop.png   no endpoint: the reason in Settings
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _boot,
    _get,
    _terminate,
    e2e_workdir,
    shot,
)
from tests.fixtures.whisper_fake import FakeWhisper

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

#: How often the page re-posts its growing take. Pinned short so the walk sees
#: a partial land without waiting on the shipped 1.5 s cadence.
PARTIAL_S = 0.3

#: What the *live* transcription server answered when this story was walked by
#: hand — capitalised, and with a full stop nobody said. `src.voice` trims the
#: trailing stop, without which `next week.` is not a date phrase and the
#: spoken due date silently disappears; the fake answers the real shape so the
#: story proves that rather than a tidy string.
HEARD = " Buy a new filter for the dehumidifier next week.\n"
SPOKEN = "Buy a new filter for the dehumidifier next week"
TITLE = "Buy a new filter for the dehumidifier"
#: What the endpoint answers to the *first* passes, while the sentence is still
#: landing. A partial is a shorter transcript of a shorter take — this is what
#: makes the live line visibly different from the final one.
PARTIAL_HEARD = " Buy a new filter"
PARTIAL_SPOKEN = "Buy a new filter"
PHONE_HEARD = "Collect the parcel tomorrow."
PHONE_SPOKEN = "Collect the parcel tomorrow"
PHONE_TITLE = "Collect the parcel"

#: Stands in for the microphone — a **real** `MediaStream`, because `voice.js`
#: runs it through `createMediaStreamSource` and an AudioWorklet. A tone from
#: an `AudioBufferSourceNode` into a `MediaStreamAudioDestinationNode` is a
#: genuine live capture as far as the page is concerned, so the worklet tap,
#: the resample, the normalise and the WAV encode under test are the shipped
#: ones rather than a shortcut around them.
FAKE_MIC = """
(() => {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => {
        const ctx = new Ctx();
        const seconds = 4;
        const buf = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < data.length; i++) data[i] = Math.sin(i * 0.06) * 0.4;
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.loop = true;                 // outlast any length of walk
        const dest = ctx.createMediaStreamDestination();
        src.connect(dest);
        src.start();
        return dest.stream;
      },
    },
  });
})();
"""


class VoiceInstance:
    def __init__(self, base: str, whisper: FakeWhisper | None) -> None:
        self.base = base
        self.whisper = whisper


def _instance(name: str, *, transcribe_url: str) -> Iterator[str]:
    from tests.fixtures.seed import seed_db

    work = e2e_workdir(name)
    db = work / "tasks.db"
    seed_db(db, E2E_ANCHOR)
    cfg = write_test_config(
        work / "config.json", transcribe_url=transcribe_url,
        partial_interval_seconds=PARTIAL_S,
    )
    proc, base, log = _boot(work, db, cfg)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="module")
def voice_webapp() -> Iterator[VoiceInstance]:
    """A seeded instance whose transcribe endpoint is the fake — never the
    real hub on :8000, and never the real whisper server on :8090."""
    with FakeWhisper(text=HEARD) as whisper:
        for base in _instance("voice", transcribe_url=whisper.url):
            yield VoiceInstance(base, whisper)


@pytest.fixture(scope="module")
def voiceless_webapp() -> Iterator[VoiceInstance]:
    """The install a fresh clone has: no ``voice.transcribe_url`` at all."""
    for base in _instance("voice-off", transcribe_url=""):
        yield VoiceInstance(base, None)


def _open_add(page: Page):
    """The + in the strip opens the add dialog, as a user would.

    Every pane carries its own + and only the visible pane's can be pressed —
    which is the Board on the desktop and Today on a coarse pointer, so the
    visible one is the one to click rather than a pane named here.
    """
    page.locator(".quick-add-btn:visible").first.click()
    dialog = page.locator("#quickAdd")
    expect(dialog).to_be_visible()
    return dialog


def _open_card(page: Page, card_id: str):
    card = page.locator(f"#{card_id}")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


def test_say_the_task(
    voice_webapp: VoiceInstance, voiceless_webapp: VoiceInstance,
    browser: Browser, shots: Path,
) -> None:
    inst = voice_webapp
    base = inst.base
    due = (E2E_ANCHOR + timedelta(days=7)).isoformat()

    # The install can reach a transcription endpoint, and says so before
    # anything is clicked.
    st = _get(base, "/api/status")["voice"]
    assert st["enabled"] is True and st["reason"] is None
    # The hub is the primary, and the status says so — "parakeet or the local
    # CPU whisper?" is answerable from this one call (#144). The live-transcript
    # cadence rides the same call, so the page never hardcodes one (#146).
    assert st["url"] == inst.whisper.url and st["serving"] == "hub"
    assert st["partial_interval_seconds"] == PARTIAL_S

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(FAKE_MIC)
    page: Page = ctx.new_page()
    page.goto(base + "/")

    # 1. the add dialog: the mic is live, and no hint is claiming otherwise
    dialog = _open_add(page)
    mic = dialog.locator(".quick-add-mic")
    line = dialog.locator(".quick-add-input")
    expect(mic).to_be_enabled()
    expect(mic).to_have_attribute("title", "Dictate (click to start)")
    expect(mic).to_have_attribute("aria-pressed", "false")
    expect(dialog.locator(".quick-add-voice-hint")).to_be_hidden()
    shot(page, shots / "story-22-voice-1-desktop.png")

    # 2. one click starts it: the button is red, the glyph is a stop square,
    #    and the words arrive on the line *while it is still recording* — the
    #    whole point of #146. The partial is shown provisionally
    #    (`.is-dictating`) and carries no parse: no date appears yet.
    inst.whisper.text = PARTIAL_HEARD
    mic.click()
    expect(mic).to_have_class(re.compile(r"is-recording"))
    expect(mic).to_have_attribute("aria-pressed", "true")
    expect(mic.locator("use")).to_have_attribute("href", "#i-square")
    expect(line).to_have_value(PARTIAL_SPOKEN)
    expect(line).to_have_class(re.compile(r"is-dictating"))
    expect(dialog.locator(".quick-add-due")).to_have_value("")
    shot(page, shots / "story-22-voice-2-desktop.png")

    # A partial really was a request of its own, and it asked for the words
    # alone — the rolling pass must not be parsing a fragment once a second.
    partials = [r for r in inst.whisper.requests]
    assert len(partials) >= 1
    assert all(r["file"][:4] == b"RIFF" for r in partials)

    # 3. click again: the line settles on the full transcript, no longer
    #    provisional, and the parse rides along — the Due field carries next
    #    week's date, correctable, not a chip.
    inst.whisper.text = HEARD
    posted_before_stop = len(inst.whisper.requests)
    mic.click()
    expect(line).to_have_value(SPOKEN)
    expect(line).not_to_have_class(re.compile(r"is-dictating"))
    expect(dialog.locator(".quick-add-due")).to_have_value(due)
    expect(mic).not_to_have_class(re.compile(r"is-recording|is-working"))
    expect(mic).to_have_attribute("aria-pressed", "false")
    expect(mic.locator("use")).to_have_attribute("href", "#i-mic")
    shot(page, shots / "story-22-voice-3-desktop.png")

    # The final pass is its own request, and it is the one that asked to parse.
    assert len(inst.whisper.requests) > posted_before_stop
    sent = inst.whisper.requests[-1]
    # …and what reached the server was WAV, because nothing else is decoded
    assert sent["filename"] == "clip.wav" and sent["file_content_type"] == "audio/wav"
    assert sent["file"][:4] == b"RIFF" and sent["file"][8:12] == b"WAVE"
    # 16 kHz mono 16-bit, resampled in the browser from the capture rate
    assert int.from_bytes(sent["file"][24:28], "little") == 16000
    assert int.from_bytes(sent["file"][22:24], "little") == 1

    # 4. one Enter and it is a real task, in **To Do** ??? a spoken task is a
    #    hand-made one (#148); Inbox is for what arrives on its own.
    dialog.locator(".quick-add-submit").click()
    expect(dialog).to_be_hidden()
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    todo = page.locator(".board-col[data-col='todo']")
    expect(todo.locator(".trow-title", has_text=TITLE)).to_be_visible()
    shot(page, shots / "story-22-voice-4-desktop.png")

    made = [t for t in _get(base, "/api/tasks?status=todo")["items"] if t["title"] == TITLE]
    assert len(made) == 1 and made[0]["due"] == due

    # Walking away mid-recording abandons it: the mic is released, the partial
    # in flight is aborted, and no transcript is written into a dialog that is
    # no longer open.
    reopened = _open_add(page)
    reopened.locator(".quick-add-mic").click()
    expect(reopened.locator(".quick-add-mic")).to_have_class(re.compile(r"is-recording"))
    posted = len(inst.whisper.requests)
    page.keyboard.press("Escape")
    expect(reopened).to_be_hidden()
    page.wait_for_timeout(1500)
    assert len(inst.whisper.requests) == posted
    expect(page.locator("#quickAdd .quick-add-input")).to_have_value("")

    # Settings agrees with the button — one /api/status, several readers
    page.emulate_media(color_scheme="light")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("tab", name="Settings").click()
    card = _open_card(page, "voiceCard")
    expect(card.locator("#voiceCardMeta")).to_have_text("on")
    expect(card.locator("#statusVoice .status-ok")).to_have_text("reachable")
    expect(card.locator("#statusVoice")).to_contain_text("hub")
    expect(card.locator("#statusVoice")).to_contain_text("live every 0.3s")
    ctx.close()

    # 5. the phone: the same gesture, through the same one endpoint — it never
    #    needs to reach the transcription server itself.
    inst.whisper.text = PHONE_HEARD
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(FAKE_MIC)
    p: Page = phone.new_page()
    p.goto(base + "/")
    p_dialog = _open_add(p)
    p_mic = p_dialog.locator(".quick-add-mic")
    expect(p_mic).to_be_enabled()
    p_mic.click()
    expect(p_mic).to_have_class(re.compile(r"is-recording"))
    expect(p_dialog.locator(".quick-add-input")).to_have_value(PHONE_SPOKEN)
    shot(p, shots / "story-22-voice-5-phone.png")
    p_mic.click()
    expect(p_dialog.locator(".quick-add-input")).to_have_value(PHONE_SPOKEN)
    expect(p_dialog.locator(".quick-add-due")).to_have_value((E2E_ANCHOR + timedelta(days=1)).isoformat())
    p_dialog.locator(".quick-add-submit").click()
    expect(p_dialog).to_be_hidden()
    assert any(t["title"] == PHONE_TITLE for t in _get(base, "/api/tasks?status=todo")["items"])
    phone.close()

    # 6. the install with no transcription endpoint: the button is visibly off,
    #    with the reason under it — never a mic that looks live and does nothing.
    off = _get(voiceless_webapp.base, "/api/status")["voice"]
    assert off["enabled"] is False and off["reason"] == "no voice.transcribe_url in config"

    ctx2 = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx2.add_init_script(FAKE_MIC)
    p2: Page = ctx2.new_page()
    p2.goto(voiceless_webapp.base + "/")
    d2 = _open_add(p2)
    hint = d2.locator(".quick-add-voice-hint")
    expect(hint).to_be_visible()
    expect(hint).to_have_text("Voice off — no voice.transcribe_url in config")
    expect(d2.locator(".quick-add-mic")).to_be_disabled()
    shot(p2, shots / "story-22-voice-6-desktop.png")
    p2.keyboard.press("Escape")

    # 7. …and Settings says the same thing, in the same words
    p2.get_by_role("tab", name="Settings").click()
    card2 = _open_card(p2, "voiceCard")
    expect(card2.locator("#voiceCardMeta")).to_have_text("off")
    expect(card2.locator("#statusVoice .status-off")).to_have_text("not reachable")
    expect(card2.locator("#statusVoice")).to_contain_text("no voice.transcribe_url in config")
    expect(card2.locator("#statusVoiceUrl")).to_have_text("not set")
    shot(p2, shots / "story-22-voice-7-desktop.png")
    ctx2.close()
