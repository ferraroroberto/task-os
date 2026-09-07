"""Story 22 — say the task instead of typing it (issue #92).

    Open the add dialog, hold the mic, say *"buy a new filter for the
    dehumidifier next week"*, let go → the line fills in with the transcript,
    the Due field already carries next week's date, and one Enter puts it in
    Inbox. Same gesture on the phone, over the one HTTPS endpoint it already
    has. An install with no whisper server says so on the button and in
    Settings, and the mic never pretends it can record.

**Nothing real is recorded and nothing real is transcribed, but everything
between them is the shipped code.** Two things are stood in for:

  * the whisper server — ``tests/fixtures/whisper_fake.FakeWhisper``, a
    loopback endpoint speaking whisper-server's shapes. The suite must never
    depend on the fleet's ``:8090`` being up (``tests/conftest`` blanks
    ``voice.whisper_url`` for exactly that reason);
  * the microphone — an init script replaces ``getUserMedia`` and
    ``MediaRecorder`` with ones that hand back a canned WAV tone.

Everything else runs for real: the press-and-hold handling, the browser-side
decode → 16 kHz mono → WAV re-encode (``static/voice.js``), the ``POST
/api/transcribe`` body, the server-side multipart forward, the quick-add parse
that rides back with the text, the chips, and the create. That is deliberately
*more* than the issue asked for (it proposed stubbing ``/api/transcribe``
itself) — the route is the half most likely to break.

    docs/screenshots/story-22-voice-1-desktop.png   the add dialog, mic ready
    docs/screenshots/story-22-voice-2-desktop.png   holding: recording
    docs/screenshots/story-22-voice-3-desktop.png   the transcript + its parsed due
    docs/screenshots/story-22-voice-4-desktop.png   the spoken task in Inbox (dark)
    docs/screenshots/story-22-voice-5-phone.png     the same gesture on the phone
    docs/screenshots/story-22-voice-6-desktop.png   no whisper: the reason on the button
    docs/screenshots/story-22-voice-7-desktop.png   no whisper: the reason in Settings
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

#: What the *live* whisper server answered when this story was walked by hand
#: — capitalised, and with a full stop nobody said. `src.voice` trims the
#: trailing stop, without which `next week.` is not a date phrase and the
#: spoken due date silently disappears; the fake answers the real shape so the
#: story proves that rather than a tidy string.
HEARD = " Buy a new filter for the dehumidifier next week.\n"
SPOKEN = "Buy a new filter for the dehumidifier next week"
TITLE = "Buy a new filter for the dehumidifier"
PHONE_HEARD = "Collect the parcel tomorrow."
PHONE_SPOKEN = "Collect the parcel tomorrow"
PHONE_TITLE = "Collect the parcel"

#: Stands in for the microphone. `MediaRecorder` hands back a one-second 48 kHz
#: WAV tone, which is a real encoded file the page's own `decodeAudioData`
#: decodes — so the resample-and-re-encode path under test is the shipped one,
#: not a shortcut around it.
FAKE_MIC = """
(() => {
  const RATE = 48000, SECONDS = 1;
  const n = RATE * SECONDS;
  const buf = new ArrayBuffer(44 + n * 2);
  const view = new DataView(buf);
  const ascii = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  ascii(0, 'RIFF'); view.setUint32(4, 36 + n * 2, true); ascii(8, 'WAVEfmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, 'data'); view.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) view.setInt16(44 + i * 2, Math.sin(i * 0.06) * 12000, true);
  const CLIP = new Blob([buf], { type: 'audio/wav' });

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
  });

  window.MediaRecorder = class {
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/wav'; this._on = {}; }
    addEventListener(type, fn) { (this._on[type] = this._on[type] || []).push(fn); }
    _emit(type, ev) { (this._on[type] || []).forEach(fn => fn(ev)); }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this._emit('dataavailable', { data: CLIP });
      this._emit('stop', {});
    }
  };
})();
"""


class VoiceInstance:
    def __init__(self, base: str, whisper: FakeWhisper | None) -> None:
        self.base = base
        self.whisper = whisper


def _instance(name: str, *, whisper_url: str) -> Iterator[str]:
    from tests.fixtures.seed import seed_db

    work = e2e_workdir(name)
    db = work / "tasks.db"
    seed_db(db, E2E_ANCHOR)
    cfg = write_test_config(work / "config.json", whisper_url=whisper_url)
    proc, base, log = _boot(work, db, cfg)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="module")
def voice_webapp() -> Iterator[VoiceInstance]:
    """A seeded instance whose whisper endpoint is the fake — never :8090."""
    with FakeWhisper(text=HEARD) as whisper:
        for base in _instance("voice", whisper_url=whisper.url):
            yield VoiceInstance(base, whisper)


@pytest.fixture(scope="module")
def voiceless_webapp() -> Iterator[VoiceInstance]:
    """The install a fresh clone has: no ``voice.whisper_url`` at all."""
    for base in _instance("voice-off", whisper_url=""):
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

    # The install can reach a whisper server, and says so before anything is held.
    st = _get(base, "/api/status")["voice"]
    assert st["enabled"] is True and st["reason"] is None
    assert st["url"] == inst.whisper.url

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(FAKE_MIC)
    page: Page = ctx.new_page()
    page.goto(base + "/")

    # 1. the add dialog: the mic is live, and no hint is claiming otherwise
    dialog = _open_add(page)
    mic = dialog.locator(".quick-add-mic")
    expect(mic).to_be_enabled()
    expect(mic).to_have_attribute("title", "Hold to dictate")
    expect(dialog.locator(".quick-add-voice-hint")).to_be_hidden()
    shot(page, shots / "story-22-voice-1-desktop.png")

    # 2. hold it: the button says it is listening
    mic.hover()
    page.mouse.down()
    expect(mic).to_have_class(re.compile(r"is-recording"))
    shot(page, shots / "story-22-voice-2-desktop.png")

    # 3. let go: the line fills with what was heard and the parse rides along —
    #    the Due field carries next week's date, correctable, not a chip.
    page.mouse.up()
    expect(dialog.locator(".quick-add-input")).to_have_value(SPOKEN)
    expect(dialog.locator(".quick-add-due")).to_have_value(due)
    expect(mic).not_to_have_class(re.compile(r"is-recording|is-working"))
    shot(page, shots / "story-22-voice-3-desktop.png")

    # …and what reached the server was WAV, because whisper reads nothing else
    sent = inst.whisper.requests[-1]
    assert sent["filename"] == "clip.wav" and sent["file_content_type"] == "audio/wav"
    assert sent["file"][:4] == b"RIFF" and sent["file"][8:12] == b"WAVE"
    # 16 kHz mono 16-bit, converted in the browser from the 48 kHz recording
    assert int.from_bytes(sent["file"][24:28], "little") == 16000
    assert int.from_bytes(sent["file"][22:24], "little") == 1

    # 4. one Enter and it is a real Inbox task, with the date it was spoken with
    dialog.locator(".quick-add-submit").click()
    expect(dialog).to_be_hidden()
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    inbox = page.locator(".board-col[data-col='inbox']")
    expect(inbox.locator(".trow-title", has_text=TITLE)).to_be_visible()
    shot(page, shots / "story-22-voice-4-desktop.png")

    made = [t for t in _get(base, "/api/tasks?status=inbox")["items"] if t["title"] == TITLE]
    assert len(made) == 1 and made[0]["due"] == due

    # Walking away mid-recording abandons it. Closing the dialog stops the
    # mic's tracks, which stops the recorder too — so its `stop` event still
    # fires, and without a guard it would upload a clip nobody asked for and
    # write the transcript into a dialog that is no longer open.
    posted = len(inst.whisper.requests)
    reopened = _open_add(page)
    reopened.locator(".quick-add-mic").hover()
    page.mouse.down()
    expect(reopened.locator(".quick-add-mic")).to_have_class(re.compile(r"is-recording"))
    page.keyboard.press("Escape")
    expect(reopened).to_be_hidden()
    page.mouse.up()
    page.wait_for_timeout(1500)
    assert len(inst.whisper.requests) == posted
    expect(page.locator("#quickAdd .quick-add-input")).to_have_value("")

    # Settings agrees with the button — one /api/status, two readers
    page.emulate_media(color_scheme="light")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("tab", name="Settings").click()
    card = _open_card(page, "voiceCard")
    expect(card.locator("#voiceCardMeta")).to_have_text("on")
    expect(card.locator("#statusVoice .status-ok")).to_have_text("reachable")
    ctx.close()

    # 5. the phone: the same gesture, through the same one endpoint — it never
    #    needs to reach the whisper server itself.
    inst.whisper.text = PHONE_HEARD
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(FAKE_MIC)
    p: Page = phone.new_page()
    p.goto(base + "/")
    p_dialog = _open_add(p)
    p_mic = p_dialog.locator(".quick-add-mic")
    expect(p_mic).to_be_enabled()
    p_mic.dispatch_event("pointerdown")
    expect(p_mic).to_have_class(re.compile(r"is-recording"))
    p_mic.dispatch_event("pointerup")
    expect(p_dialog.locator(".quick-add-input")).to_have_value(PHONE_SPOKEN)
    expect(p_dialog.locator(".quick-add-due")).to_have_value((E2E_ANCHOR + timedelta(days=1)).isoformat())
    shot(p, shots / "story-22-voice-5-phone.png")
    p_dialog.locator(".quick-add-submit").click()
    expect(p_dialog).to_be_hidden()
    assert any(t["title"] == PHONE_TITLE for t in _get(base, "/api/tasks?status=inbox")["items"])
    phone.close()

    # 6. the install with no whisper server: the button is visibly off, with
    #    the reason under it — never a mic that looks live and does nothing.
    off = _get(voiceless_webapp.base, "/api/status")["voice"]
    assert off["enabled"] is False and off["reason"] == "no voice.whisper_url in config"

    ctx2 = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx2.add_init_script(FAKE_MIC)
    p2: Page = ctx2.new_page()
    p2.goto(voiceless_webapp.base + "/")
    d2 = _open_add(p2)
    hint = d2.locator(".quick-add-voice-hint")
    expect(hint).to_be_visible()
    expect(hint).to_have_text("Voice off — no voice.whisper_url in config")
    expect(d2.locator(".quick-add-mic")).to_be_disabled()
    shot(p2, shots / "story-22-voice-6-desktop.png")
    p2.keyboard.press("Escape")

    # 7. …and Settings says the same thing, in the same words
    p2.get_by_role("tab", name="Settings").click()
    card2 = _open_card(p2, "voiceCard")
    expect(card2.locator("#voiceCardMeta")).to_have_text("off")
    expect(card2.locator("#statusVoice .status-off")).to_have_text("not reachable")
    expect(card2.locator("#statusVoice")).to_contain_text("no voice.whisper_url in config")
    expect(card2.locator("#statusVoiceUrl")).to_have_text("not set")
    shot(p2, shots / "story-22-voice-7-desktop.png")
    ctx2.close()
