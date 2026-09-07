/* task-os — voice quick-add: hold the mic, say the line (#92).
 *
 * `mountMic(button, hint, opts)` turns one button into a press-and-hold
 * dictation control and owns everything between the press and the transcript:
 *
 *   press  → getUserMedia + MediaRecorder start   (`.is-recording`)
 *   release→ stop, decode, resample, POST         (`.is-working`)
 *   answer → opts.onResult({text, parse})         (the caller fills the line)
 *
 * The re-encode is also where a quiet clip is lifted (see `normalize`) —
 * whisper answers a near-silent recording with a confident hallucination
 * rather than an error, so level is a correctness concern, not a nicety.
 *
 * **Why the recording is re-encoded here.** whisper.cpp's `whisper-server`
 * decodes WAV and answers a bare `400 Invalid request` to anything else — a
 * probe against the live :8090 took 200 for a 16 kHz WAV and 400 for both
 * formats a browser can record (webm/opus on Chrome, mp4/aac on iOS Safari).
 * Converting server-side would mean an ffmpeg subprocess in the webapp; the
 * browser already has a decoder for its own recording, so it decodes the blob
 * (`decodeAudioData`), downmixes to mono, box-filters down to 16 kHz and
 * writes a PCM WAV — ~50 lines, no dependency, identical on both engines.
 *
 * Never a dead button: every way this can fail — no `voice.whisper_url`, a
 * whisper server that is not answering, a browser with no MediaRecorder, a
 * page that is not a secure context, a denied mic permission — leaves the
 * button visible and disabled with the reason in `hint`, which is the same
 * sentence `/api/status` gives the Settings card.
 */

'use strict';

import { api } from './api.js';

/** What whisper wants, and what a phrase needs: mono speech, 16 kHz. */
const TARGET_RATE = 16000;
/** Below this a recording is a mis-tap, not a phrase. */
const MIN_SAMPLES = TARGET_RATE / 4;
/** How long a status verdict is reused before /api/status is asked again.
 *  The server caches its own probe for 15 s; this only keeps the dialog from
 *  re-asking on every open in one working minute. */
const STATUS_TTL_MS = 30000;

let cached = null;      // {at: epoch ms, state: {enabled, reason}}

/** The install's voice state, at most once every STATUS_TTL_MS. */
async function voiceState() {
  if (cached && Date.now() - cached.at < STATUS_TTL_MS) return cached.state;
  let state;
  try {
    const st = await api('/api/status');
    state = st.voice || { enabled: false, reason: 'this install reports no voice status' };
  } catch (err) {
    // The status call itself failed: that is not "voice is off", it is "not
    // established" — say which, rather than blaming whisper.
    state = { enabled: false, reason: 'could not read the app status — ' + (err.message || 'unknown') };
  }
  cached = { at: Date.now(), state: state };
  return state;
}

/** What this browser cannot do, in the same sentence shape — or `null`. */
function browserBlocker() {
  if (!window.isSecureContext) return 'this page is not a secure context — the browser only allows a microphone over HTTPS or on localhost';
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'this browser exposes no microphone (navigator.mediaDevices)';
  if (typeof window.MediaRecorder === 'undefined') return 'this browser has no MediaRecorder';
  if (!(window.AudioContext || window.webkitAudioContext)) return 'this browser has no Web Audio decoder';
  return null;
}

// ------------------------------------------------------------ WAV encoding

/** One mono Float32 track at `rate`, from whatever the browser decoded.
 *  Channels are averaged (a phone's stereo mic is one voice twice). */
function toMono(buffer) {
  const n = buffer.length;
  const out = new Float32Array(n);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < n; i++) out[i] += data[i];
  }
  if (buffer.numberOfChannels > 1) {
    for (let i = 0; i < n; i++) out[i] /= buffer.numberOfChannels;
  }
  return out;
}

/** Downsample by averaging each output sample's whole input window.
 *  Picking every Nth sample instead would alias 48 kHz speech audibly; a box
 *  filter is crude but it is a filter, and it is 8 lines. */
function resample(samples, from, to) {
  if (from === to) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

/** Bring a quiet recording up to a level whisper can actually read.
 *
 * Whisper does not fail on quiet audio, it *invents*: fed a −35 dBFS clip it
 * answers "Thank you." with complete confidence, which is far worse than an
 * error. That level is not hypothetical — the browser's own capture chain
 * (AGC + noise suppression) delivered exactly it during the live walk of this
 * feature, and a phone held at arm's length is the same situation.
 *
 * Peak normalisation, with two guards: nothing below `SILENCE` is touched (an
 * empty room must stay empty rather than become amplified hiss, so "nothing
 * was heard" can still be said honestly), and the gain is capped so a genuinely
 * near-silent clip is lifted, not detonated.
 */
const SILENCE = 0.002;
const MAX_GAIN = 30;
const TARGET_PEAK = 0.97;

function normalize(samples) {
  let peak = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = Math.abs(samples[i]);
    if (v > peak) peak = v;
  }
  if (peak < SILENCE || peak >= TARGET_PEAK) return samples;
  const gain = Math.min(TARGET_PEAK / peak, MAX_GAIN);
  for (let i = 0; i < samples.length; i++) samples[i] *= gain;
  return samples;
}

/** A 16-bit PCM WAV file (44-byte canonical header + samples). */
function encodeWav(samples, rate) {
  const bytes = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(bytes);
  const ascii = function (offset, text) {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  ascii(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, 'WAVEfmt ');
  view.setUint32(16, 16, true);          // PCM header size
  view.setUint16(20, 1, true);           // format: PCM
  view.setUint16(22, 1, true);           // channels: mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);    // byte rate (mono, 2 bytes/sample)
  view.setUint16(32, 2, true);           // block align
  view.setUint16(34, 16, true);          // bits per sample
  ascii(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([bytes], { type: 'audio/wav' });
}

/** The recorded blob → the 16 kHz mono WAV whisper can read. */
export async function toWav(blob) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const samples = resample(toMono(decoded), decoded.sampleRate, TARGET_RATE);
    if (samples.length < MIN_SAMPLES) return null;      // a tap, not a phrase
    return encodeWav(normalize(samples), TARGET_RATE);
  } finally {
    if (ctx.close) ctx.close();
  }
}

// ------------------------------------------------------------- the button

/**
 * Wire one press-and-hold mic button.
 * @param {HTMLButtonElement} btn   the `.quick-add-mic` button
 * @param {HTMLElement} hint        where the off-reason is spelled out
 * @param {{onResult: (r: {text: string, parse: object}) => void,
 *          onError: (message: string) => void}} opts
 * @returns {{refresh: () => Promise<void>, cancel: () => void}}
 */
export function mountMic(btn, hint, opts) {
  let recorder = null;
  let stream = null;
  let chunks = [];
  let held = false;         // a press is in flight (pointer or key)
  let busy = false;         // a clip is being decoded / transcribed
  let ready = false;        // the install + this browser can actually record

  function say(reason) {
    hint.textContent = reason ? 'Voice off — ' + reason : '';
    hint.hidden = !reason;
    btn.disabled = !!reason;
    btn.title = reason ? 'Voice off — ' + reason : 'Hold to dictate';
  }

  /** Ask the install (cached) and this browser what voice can do here. */
  async function refresh() {
    const blocked = browserBlocker();
    if (blocked) { ready = false; say(blocked); return; }
    const state = await voiceState();
    ready = !!state.enabled;
    say(ready ? null : (state.reason || 'unknown'));
  }

  function setState(cls) {
    btn.classList.toggle('is-recording', cls === 'recording');
    btn.classList.toggle('is-working', cls === 'working');
    btn.setAttribute('aria-label', cls === 'recording' ? 'Recording — release to transcribe'
      : cls === 'working' ? 'Transcribing…' : 'Hold to dictate');
  }

  function release() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    recorder = null;
  }

  async function start() {
    if (held || busy || !ready) return;
    held = true;
    chunks = [];
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      held = false;
      // A refused microphone is a standing state, not a one-off toast: the
      // button has to stop claiming it can record.
      ready = false;
      say('the browser refused the microphone — ' + (err.message || err.name || 'permission denied'));
      return;
    }
    if (!held) { release(); return; }        // released before the mic opened
    recorder = new MediaRecorder(stream);
    recorder.addEventListener('dataavailable', function (ev) {
      if (ev.data && ev.data.size) chunks.push(ev.data);
    });
    recorder.addEventListener('stop', function () { finish(); });
    recorder.start();
    setState('recording');
  }

  function stop() {
    if (!held) return;
    held = false;
    if (recorder && recorder.state !== 'inactive') recorder.stop();   // → finish()
    else release();
  }

  async function finish() {
    const blob = new Blob(chunks, { type: (recorder && recorder.mimeType) || 'audio/webm' });
    release();
    chunks = [];
    if (!blob.size) { setState(''); return; }
    busy = true;
    setState('working');
    btn.disabled = true;
    try {
      const wav = await toWav(blob);
      if (!wav) { opts.onError('Too short — hold the mic while you speak'); return; }
      const res = await fetch('/api/transcribe', {
        method: 'POST', body: wav, cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'audio/wav' },
      });
      const body = await res.json().catch(function () { return null; });
      if (!res.ok) {
        const e = (body && body.error) || {};
        // The endpoint just told us something the cached status does not know
        // yet — drop it so the next open re-probes rather than showing "on".
        cached = null;
        opts.onError(e.message || ('Transcription failed (HTTP ' + res.status + ')'));
        refresh();
        return;
      }
      if (!body || !body.text) { opts.onError('Nothing was heard — try again closer to the mic'); return; }
      opts.onResult(body);
    } catch (err) {
      opts.onError(err.message || 'Could not transcribe the recording');
    } finally {
      busy = false;
      setState('');
      btn.disabled = !ready;
    }
  }

  // Pointer hold. The capture is what makes "release" mean release: without
  // it a finger (or a mouse) that slides off the button before letting go
  // sends `pointerup` somewhere else and leaves the microphone running.
  btn.addEventListener('pointerdown', function (ev) {
    ev.preventDefault();
    if (btn.setPointerCapture && ev.pointerId != null) {
      try { btn.setPointerCapture(ev.pointerId); } catch (_) { /* not capturable — the events still land */ }
    }
    start();
  });
  btn.addEventListener('pointerup', function () { stop(); });
  btn.addEventListener('pointercancel', function () { stop(); });
  // The keyboard analogue of a hold: Space/Enter down starts, up stops.
  // `repeat` is what a held key sends after the first event — `start()` is
  // guarded anyway, but ignoring it keeps the intent readable.
  btn.addEventListener('keydown', function (ev) {
    if (ev.repeat || (ev.key !== ' ' && ev.key !== 'Enter')) return;
    ev.preventDefault();
    start();
  });
  btn.addEventListener('keyup', function (ev) {
    if (ev.key !== ' ' && ev.key !== 'Enter') return;
    stop();
  });
  // A button click is the pair of events above; nothing extra should fire.
  btn.addEventListener('click', function (ev) { ev.preventDefault(); });

  // Until the first `refresh()` answers, the button is off with no claim
  // either way — an unasked question is not a reason.
  btn.disabled = true;
  btn.title = 'Checking the whisper server…';
  hint.hidden = true;
  return { refresh: refresh, cancel: function () { held = false; release(); setState(''); } };
}
