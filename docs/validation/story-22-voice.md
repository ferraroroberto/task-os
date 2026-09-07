# Story 22 — Say the task instead of typing it (#92)

**Story.** Hands busy, phone in one hand, standing in front of the dehumidifier: open the add dialog, **hold the mic**, say *"buy a new filter for the dehumidifier next week"*, let go. The line fills with what was said and the **Due** field already carries next week's date — the same quick-add split typing it would have produced — one confirming Enter from a real Inbox task. The same gesture on the phone, over the one Tailscale HTTPS endpoint it already has: the clip goes browser → task-os → the fleet's [local-llm-hub](https://github.com/ferraroroberto/local-llm-hub), which picks the transcription model, and the phone never needs to reach it itself. An install with no transcription endpoint says so **on the button**, with the reason, and in Settings — never a mic that looks live and does nothing.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open the add dialog | The mic sits inside line 1, enabled, titled *Hold to dictate*; no hint under the field |
| 2 | Press and hold it | The button tints and pulses (`.is-recording`); the microphone is open |
| 3 | Say the line, release | Line 1 = the transcript; **Due** = next week's date, correctable; the button returns to rest. What reached the server was **16 kHz mono WAV**, converted in the browser — whisper-server decodes nothing else |
| 4 | Enter / **Add** | An ordinary Inbox task, titled without the date phrase, due the spoken date |
| 5 | Hold the mic, then close the dialog without releasing | The recording is **abandoned**: nothing is uploaded, and no transcript lands in a dialog that is no longer open |
| 6 | Settings → *Voice quick-add* | `on`; Transcription = **reachable · hub** · checked <time>; Endpoint = the configured URL. `hub` vs `local whisper (fallback)` is what says whether parakeet or the CPU whisper is answering |
| 7 | Phone (390×844), same gesture | Identical: transcript on the line, parsed due, task created. The phone talks only to this app |
| 8 | An install with no `voice.transcribe_url` | The mic is visibly disabled and *"Voice off — no voice.transcribe_url in config"* sits under the field; the Settings card reads `off` with the same reason and *Endpoint: not set* |
| 9 | Every endpoint down, with the URLs still configured | `/api/status` → `enabled: false` + the reason; the mic disabled with that reason; `POST /api/transcribe` → **503** `voice_unavailable` naming the endpoint — never a silent nothing |

## Proof

- **Screenshots:** [1](../screenshots/story-22-voice-1-desktop.png) (dialog, mic ready) · [2](../screenshots/story-22-voice-2-desktop.png) (holding — recording) · [3](../screenshots/story-22-voice-3-desktop.png) (transcript + its parsed due) · [4](../screenshots/story-22-voice-4-desktop.png) (the spoken task in Inbox, dark) · [5](../screenshots/story-22-voice-5-phone.png) (the phone) · [6](../screenshots/story-22-voice-6-desktop.png) (no whisper: the reason on the button) · [7](../screenshots/story-22-voice-7-desktop.png) (no whisper: the reason in Settings).
- **E2e:** `tests/e2e/test_story_22_voice.py` — two disposable seeded instances (one pointed at `tests/fixtures/whisper_fake.FakeWhisper`, one with `voice.transcribe_url` blank), Chromium 1440×900 light + a dark shot, then a 390-wide touch context. **Never the real hub or whisper server** — `tests/conftest.write_test_config` blanks both `voice` endpoints suite-wide. The microphone is the only browser thing stubbed (an init script returning a canned WAV); the press-and-hold, the decode → mono → 16 kHz → normalise → WAV re-encode, the `POST /api/transcribe`, the multipart forward, the parse that rides back and the create are all the shipped code. The fake answers the transcript **with whisper's real punctuation** (`" Buy … next week.\n"`), so the story proves the trailing stop is handled rather than assuming a tidy string.
- **Unit:** `tests/test_voice.py` (19) — URL addressability, the multipart bytes, both response shapes, the punctuation trim and the due it saves, the probe's reachable / refused / timed-out / unconfigured reasons, the cache, the forward, refusal-vs-silence as different errors, the cache drop after a failed POST, empty/oversized bodies, and at route level: the text + parse in one call, each failure's own status, the Content-Length pre-check, `/api/status`'s `voice`, and that `/api/transcribe` is closed to a non-loopback caller with no token · `tests/test_cli.py::test_voice_status_over_both_backends` (identical shape from both backends).

## Live walk (the real whisper server, 2026-09-07)

Not a fixture: the fleet's `whisper-server` (`ggml-large-v3-turbo`) running on `127.0.0.1:8090`, a disposable instance configured against it, and headed Chrome driven by hand.

- **Format, established first.** `POST`ing the same phrase three ways to the live endpoint: **200** `{"text": …}` for 16 kHz WAV, **400 `Invalid request`** for webm/opus, **400** for mp4/aac. The issue assumed whisper accepted the browser formats; it does not, which is why the conversion lives in `static/voice.js`. Verified before a line of the UI was written.
- **The happy path, end to end.** A real `MediaStream` (a real WAV of speech fed through Web Audio, so `MediaRecorder` encoded webm/opus for real) → hold 4 s → release. Transcript on the line: **`Buy a new filter for the dehumidifier next week`**. Due: **`2026-09-14`**. Toast: *Added #51 Buy a new filter for the dehumidifier*. Settings: `on` · reachable.
- **Two defects the live walk found, both fixed here.**
  - The live server answers *"Buy a new filter for the dehumidifier next week**.**"* — and `next week.` is not a date phrase, so every spoken due date silently vanished. `src.voice.clean_transcript` trims trailing sentence punctuation (voice only; a *typed* "next week." still means what it says).
  - The browser's own capture chain delivered the clip **31 dB down**, and whisper does not fail on quiet audio — it invents, confidently: *"Thank you."*, then *"The End"*. `static/voice.js` now peak-normalises before encoding, with a silence floor so an empty room stays empty.
- **The failure path, live.** Whisper stopped, URL still configured: `/api/status` → `enabled: false` + *"127.0.0.1:8090 did not answer within 1.5s — whisper may be down, or the port may be busy (it is shared with the fleet's other transcriber)"*; the same sentence under the mic, which is disabled; `POST /api/transcribe` → **503** `voice_unavailable` naming the endpoint and carrying the socket error. A third finding fixed here: a dead loopback port takes **~2 s** to report *refused* on this machine, so a probe short enough for the UI to wait on genuinely cannot tell "down" from "busy" — the reason now names both possibilities instead of asserting the one it has not established.

## Live walk round 2 — through the hub (#144, 2026-09-07)

The first round pointed straight at the local whisper-server on `:8090`, which bypasses the hub's transcribe role, its observability ring, and — as it turns out — works only when a server that is normally *not* running here happens to be up. Re-walked against the hub:

- **`/api/status`** → `{"enabled": true, "serving": "hub", "url": "http://127.0.0.1:8000/…"}`; Settings reads *reachable · hub*.
- **The same headed walk** (real speech through a real `MediaStream`, real `MediaRecorder`, real conversion): transcript `Buy a new filter for the dehumidifier next week`, Due `2026-09-14`, task created. The breadcrumb names what actually served it:

  ```
  voice: 126764 bytes of audio/wav → 47 chars in 0.3 s via parakeet@mac-mini-m4
  ```

  **0.3 s on parakeet**, against seconds on the local whisper server.
- **The fallback, live.** Primary pointed at a dead port, fallback at the real hub: the log warns that the primary did not answer, the clip goes to the fallback, the transcript is correct, and `/api/status` reports `serving: "fallback"`. Proven end to end, not only against a fixture.
- **Format re-verified against the hub**, not assumed from whisper: webm/opus gets `400 audio conversion failed` there too, so the browser-side WAV conversion stays required.

## Result

*(filled in at ship time — see the row in `docs/validation.md`.)*

## What this story does **not** cover

- **A real microphone, and a real iPhone.** Every walk above injected real speech as a real audio stream, which exercises `MediaRecorder`, the decode, the resample and the encode — but not a physical microphone, and not iOS Safari's own recorder (mp4/aac, and its `decodeAudioData`). Owner's checklist.
- **Voice over the Tailscale endpoint from an actual phone.** The e2e phone leg is a 390-wide touch context on loopback; the HTTPS + cookie path it would use is story 07's, unchanged by this work.
- **Whisper's accuracy.** One phrase, one voice, one language was transcribed correctly. This story proves the plumbing, not the model.

## Deliberate limits (from the issue)

Dictating descriptions and comments, voice through the global hotkey window, and translation are all out of scope. The drawer's comment composer is deliberately untouched.
