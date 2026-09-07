/* task-os — voice quick-add: click the mic, watch the line fill in (#92, #146).
 *
 * `mountMic(button, hint, opts)` turns one button into a dictation control and
 * owns everything between the click and the transcript:
 *
 *   click  → mic + audio graph running        (`.is-recording`, a stop square)
 *   …while you speak, every `partial_interval_seconds`:
 *            the take so far → POST ?parse=0  → opts.onPartial(text)
 *   click  → the whole take → POST            (`.is-working`)
 *   answer → opts.onResult({text, parse})     (the caller settles the line)
 *
 * **Why the transcript can appear live without a streaming server.**
 * `app-launcher` gets live partials from a server-side session — chunk uploads,
 * an SSE stream, a `/finish` call — but all its session host actually does is
 * re-run the model over the *whole accumulated take* every second or so. The
 * session only exists because that app's audio arrives as webm and needs
 * ffmpeg server-side to become WAV. This app already encodes WAV **here**, so
 * the same effect needs no session, no chunk store, no SSE and no new route:
 * the page re-encodes its own growing buffer and re-posts it. parakeet answers
 * a short clip in a fraction of a second, which is what makes that affordable.
 *
 * **Why raw samples rather than a MediaRecorder blob.** A partial needs a
 * snapshot that decodes *mid-take*, and a container cut off mid-stream does not
 * reliably decode (iOS Safari's fragmented mp4 certainly does not). So the mic
 * is tapped through an AudioWorklet (`voice-worklet.js`) for Float32 blocks,
 * which have nothing to truncate — a complete WAV can be written from whatever
 * has arrived at any moment. `MediaRecorder` and `decodeAudioData` are gone
 * from the pipeline entirely; this is one decoding step *fewer* than #92 had.
 *
 * **Why the recording is re-encoded here at all.** Both transcription
 * endpoints decode WAV and refuse everything else — a probe against the live
 * ones took 200 for a 16 kHz WAV and 400 for both formats a browser can record
 * (webm/opus on Chrome, mp4/aac on iOS Safari); the hub answers webm with
 * `400 audio conversion failed`. Converting server-side would mean an ffmpeg
 * subprocess in the webapp. The re-encode is also where a quiet clip is lifted
 * (see `normalize`) — a transcription model answers near-silent audio with a
 * confident hallucination rather than an error, so level is a correctness
 * concern, not a nicety.
 *
 * Never a dead button: every way this can fail — no `voice.transcribe_url`, no
 * transcription endpoint answering, a browser with no AudioWorklet, a page that
 * is not a secure context, a denied mic permission — leaves the button visible
 * and disabled with the reason in `hint`, which is the same sentence
 * `/api/status` gives the Settings card.
 */

'use strict';

import { api } from './api.js';

/** What the models want, and what a phrase needs: mono speech, 16 kHz. */
const TARGET_RATE = 16000;
/** Below this a recording is a mis-tap, not a phrase. */
const MIN_SAMPLES = TARGET_RATE / 4;
/** How long a status verdict is reused before /api/status is asked again.
 *  The server caches its own probe for 15 s; this only keeps the dialog from
 *  re-asking on every open in one working minute. */
const STATUS_TTL_MS = 30000;
/** Used only when `/api/status` could not say — the install owns the cadence
 *  (`voice.partial_interval_seconds`), this is just a sane last resort. */
const FALLBACK_PARTIAL_MS = 1500;
/** Every pass re-uploads the *whole* take, so the uploads grow with it. That
 *  is affordable for a quick-add line and not for a mic somebody forgot was
 *  open, so past this the live transcript stops updating rather than posting a
 *  larger file every interval. Stopping still transcribes the whole take. */
const MAX_PARTIAL_SECONDS = 120;

/** The worklet, stamped with the same cache-busting hash this module carries.
 *  Every static asset shares one fleet hash (src/static_versioning.py), and
 *  `addModule()` takes a plain string that the import rewriter never sees — so
 *  the stamp is copied off this module's own URL rather than left off. */
const WORKLET_URL = new URL(
  './voice-worklet.js' + new URL(import.meta.url).search, import.meta.url,
).href;

let cached = null;      // {at: epoch ms, state: {enabled, reason, …}}

/** The install's voice state, at most once every STATUS_TTL_MS. */
async function voiceState() {
  if (cached && Date.now() - cached.at < STATUS_TTL_MS) return cached.state;
  let state;
  try {
    const st = await api('/api/status');
    state = st.voice || { enabled: false, reason: 'this install reports no voice status' };
  } catch (err) {
    // The status call itself failed: that is not "voice is off", it is "not
    // established" — say which, rather than blaming the transcription server.
    state = { enabled: false, reason: 'could not read the app status — ' + (err.message || 'unknown') };
  }
  cached = { at: Date.now(), state: state };
  return state;
}

/** What this browser cannot do, in the same sentence shape — or `null`. */
function browserBlocker() {
  if (!window.isSecureContext) return 'this page is not a secure context — the browser only allows a microphone over HTTPS or on localhost';
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'this browser exposes no microphone (navigator.mediaDevices)';
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return 'this browser has no Web Audio (AudioContext)';
  // `audioWorklet` is a getter on the prototype, so `in` is the check that
  // works without constructing a context just to ask.
  if (!('audioWorklet' in Ctx.prototype) || typeof window.AudioWorkletNode === 'undefined') {
    return 'this browser has no AudioWorklet, which is how the microphone is read';
  }
  return null;
}

// ------------------------------------------------------------ WAV encoding

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

/** Bring a quiet recording up to a level the model can actually read.
 *
 * Transcription does not fail on quiet audio, it *invents*: fed a −35 dBFS clip
 * whisper answered "Thank you." with complete confidence, which is far worse
 * than an error. That level is not hypothetical — the browser's own capture
 * chain (AGC + noise suppression) delivered exactly it during the live walk of
 * this feature, and a phone held at arm's length is the same situation.
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

/** The blocks captured so far → one 16 kHz mono WAV, or `null` when the take
 *  is still shorter than a phrase. Called both mid-recording (a partial) and
 *  at the end (the take), which is the whole point of holding samples rather
 *  than a recording: any prefix of them is a complete file. */
export function encodeSnapshot(blocks, rate) {
  let total = 0;
  for (let i = 0; i < blocks.length; i++) total += blocks[i].length;
  const flat = new Float32Array(total);
  let at = 0;
  for (let i = 0; i < blocks.length; i++) { flat.set(blocks[i], at); at += blocks[i].length; }
  const samples = resample(flat, rate, TARGET_RATE);
  if (samples.length < MIN_SAMPLES) return null;      // a tap, not a phrase
  return encodeWav(normalize(samples), TARGET_RATE);
}

// ------------------------------------------------------------- the button

/** What the hint says while the mic is open. Deliberately **not** a running
 *  elapsed-time counter: story screenshots have to be byte-identical across
 *  two runs of one commit (docs/validation.md), and a live clock cannot be.
 *  The red pulsing stop square is what says "recording"; this says how to end
 *  it. */
const LISTENING = 'Listening… click the square to stop.';

/**
 * Wire one click-to-toggle mic button.
 * @param {HTMLButtonElement} btn   the `.quick-add-mic` button
 * @param {HTMLElement} hint        where the off-reason (and, while recording,
 *                                  how to stop) is spelled out
 * @param {{onResult: (r: {text: string, parse: object}) => void,
 *          onPartial: (text: string) => void,
 *          onStart: () => void,
 *          onError: (message: string) => void,
 *          isLive?: () => boolean}} opts  `isLive` answers "is the surface
 *          holding this button still open" — a recording whose dialog has
 *          gone is dropped rather than uploaded.
 * @returns {{refresh: () => Promise<void>, cancel: () => void}}
 */
export function mountMic(btn, hint, opts) {
  const glyph = btn.querySelector('use');
  let ctx = null;           // AudioContext, alive only while recording
  let stream = null;        // the granted MediaStream
  let node = null;          // the worklet tap
  let blocks = [];          // every Float32Array the tap has handed over
  let captured = 0;         // samples in `blocks`, the snapshot's version
  let recording = false;
  let busy = false;         // the final clip is being encoded / transcribed
  let ready = false;        // the install + this browser can actually record
  let partialMs = FALLBACK_PARTIAL_MS;   // 0 = no live transcript
  let poller = 0;           // the partial interval
  let inFlight = null;      // the AbortController of the partial in flight
  let lastSent = 0;         // `captured` at the last partial post
  let shown = 0;            // `captured` behind the transcript on screen
  // Set by `cancel()` — the surface closed while the mic was open. The flag
  // alone is not enough, because the two things that end a recording race:
  // closing the dialog can reach the button's own handlers before the dialog's
  // close handler calls `cancel()`. `opts.isLive` is the caller's own answer
  // to "is this control still on screen and wanted", so the two guards
  // together cover either order.
  let abandoned = false;
  const live = opts.isLive || function () { return true; };
  const onPartial = opts.onPartial || function () {};
  const onStart = opts.onStart || function () {};

  function setHint(text) {
    hint.textContent = text || '';
    hint.hidden = !text;
  }

  /** The standing "voice cannot record here, and this is why" state. Only
   *  this disables the button — the elapsed-time hint must never look like a
   *  reason, so it goes through `setHint` instead. */
  function say(reason) {
    setHint(reason ? 'Voice off — ' + reason : '');
    btn.disabled = !!reason;
    btn.title = reason ? 'Voice off — ' + reason : 'Dictate (click to start)';
  }

  /** Ask the install (cached) and this browser what voice can do here. */
  async function refresh() {
    const blocked = browserBlocker();
    if (blocked) { ready = false; say(blocked); return; }
    const state = await voiceState();
    ready = !!state.enabled;
    // A cadence the install did not state is not a reason to hardcode one
    // silently — but it is also not worth failing over, so the fallback is
    // used and stays a constant with a name.
    partialMs = typeof state.partial_interval_seconds === 'number'
      ? Math.round(state.partial_interval_seconds * 1000)
      : FALLBACK_PARTIAL_MS;
    say(ready ? null : (state.reason || 'unknown'));
  }

  function setState(cls) {
    btn.classList.toggle('is-recording', cls === 'recording');
    btn.classList.toggle('is-working', cls === 'working');
    if (glyph) glyph.setAttribute('href', cls === 'recording' ? '#i-square' : '#i-mic');
    btn.setAttribute('aria-pressed', cls === 'recording' ? 'true' : 'false');
    const label = cls === 'recording' ? 'Stop recording'
      : cls === 'working' ? 'Transcribing…' : 'Dictate (click to start)';
    btn.setAttribute('aria-label', label);
    if (cls !== 'working') btn.title = label;
  }

  /** Tear the audio graph down and release the microphone. Idempotent. */
  function release() {
    window.clearInterval(poller); poller = 0;
    if (node) { try { node.port.onmessage = null; node.disconnect(); } catch (_) { /* already gone */ } }
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    if (ctx && ctx.close) { try { ctx.close(); } catch (_) { /* already closed */ } }
    node = null; stream = null; ctx = null;
    recording = false;
  }

  /** One POST of the current take. `parse` is false for a partial. */
  async function post(wav, parse) {
    const control = new AbortController();
    if (!parse) inFlight = control;
    try {
      const res = await fetch('/api/transcribe' + (parse ? '' : '?parse=0'), {
        method: 'POST', body: wav, cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'audio/wav' }, signal: control.signal,
      });
      const body = await res.json().catch(function () { return null; });
      if (!res.ok) {
        const e = (body && body.error) || {};
        const err = new Error(e.message || ('Transcription failed (HTTP ' + res.status + ')'));
        err.reported = true;
        throw err;
      }
      return body;
    } finally {
      if (inFlight === control) inFlight = null;
    }
  }

  /** One rolling pass: the take so far, transcribed, shown on the line.
   *
   *  Three guards, the same ones `voice-transcriber`'s rolling worker uses:
   *  never overlap two passes, never re-transcribe audio that has not grown,
   *  and never post less than a phrase. A pass that fails is simply skipped —
   *  the final transcript on stop is the source of truth, and shouting about
   *  a dropped partial would be noise mid-sentence. */
  async function partial() {
    if (!recording || inFlight || captured === lastSent) return;
    if (captured > MAX_PARTIAL_SECONDS * ctx.sampleRate) {
      window.clearInterval(poller); poller = 0;
      return;
    }
    const version = captured;
    const wav = encodeSnapshot(blocks, ctx.sampleRate);
    if (!wav) return;
    lastSent = version;
    let body;
    try {
      body = await post(wav, false);
    } catch (_) {
      return;                      // a dropped partial costs nothing
    }
    // Late answers are dropped rather than allowed to walk the line backwards:
    // a slow pass can land after a newer, longer one.
    if (!recording || abandoned || !live() || version < shown) return;
    if (body && typeof body.text === 'string' && body.text) {
      shown = version;
      onPartial(body.text);
    }
  }

  async function start() {
    if (recording || busy || !ready) return;
    abandoned = false;
    blocks = []; captured = 0; lastSent = 0; shown = 0;
    try {
      // `channelCount: 1` here and on the node below: a phone's second channel
      // is the same voice twice, and asking the graph to downmix is cheaper
      // and more correct than averaging afterwards.
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    } catch (err) {
      // A refused microphone is a standing state, not a one-off toast: the
      // button has to stop claiming it can record.
      release();
      ready = false;
      say('the browser refused the microphone — ' + (err.message || err.name || 'permission denied'));
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    ctx = new Ctx();
    try {
      await ctx.audioWorklet.addModule(WORKLET_URL);
      node = new AudioWorkletNode(ctx, 'voice-tap', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        channelCount: 1, channelCountMode: 'explicit',
      });
    } catch (err) {
      release();
      ready = false;
      say('the microphone tap would not load — ' + (err.message || err.name || 'AudioWorklet failed'));
      return;
    }
    if (abandoned) { release(); return; }     // cancelled while the mic opened
    node.port.onmessage = function (ev) { blocks.push(ev.data); captured += ev.data.length; };
    // The graph is pull-based: a node nothing downstream listens to is not
    // guaranteed to be run at all. A muted gain into the destination is the
    // cheapest way to make the tap unambiguously live without putting the
    // microphone through the speakers.
    const muted = ctx.createGain();
    muted.gain.value = 0;
    ctx.createMediaStreamSource(stream).connect(node);
    node.connect(muted).connect(ctx.destination);
    // A context constructed after an `await` is past the click's synchronous
    // window, and an autoplay policy can hand it back suspended — in which
    // case nothing is pulled through the graph and the tap never fires.
    if (ctx.state === 'suspended' && ctx.resume) { try { await ctx.resume(); } catch (_) { /* best effort */ } }

    recording = true;
    setState('recording');
    setHint(LISTENING);
    if (partialMs > 0) poller = window.setInterval(partial, partialMs);
    onStart();
  }

  async function stop() {
    if (!recording) return;
    const rate = ctx.sampleRate;
    const wav = encodeSnapshot(blocks, rate);
    if (inFlight) inFlight.abort();          // the take is over; the partial is moot
    release();
    setHint('');
    // Nothing is uploaded for a recording that was walked away from.
    if (abandoned || !live()) { setState(''); return; }
    if (!wav) { setState(''); opts.onError('Too short — say a little more'); return; }
    busy = true;
    setState('working');
    btn.disabled = true;
    try {
      const body = await post(wav, true);
      if (abandoned || !live()) return;
      if (!body || !body.text) { opts.onError('Nothing was heard — try again closer to the mic'); return; }
      opts.onResult(body);
    } catch (err) {
      // The endpoint just told us something the cached status does not know
      // yet — drop it so the next open re-probes rather than showing "on".
      cached = null;
      opts.onError(err.message || 'Could not transcribe the recording');
      refresh();
    } finally {
      busy = false;
      setState('');
      btn.disabled = !ready;
    }
  }

  // One click toggles. Space and Enter reach this natively through the
  // button, which is why #92's bespoke key handling is gone.
  btn.addEventListener('click', function (ev) {
    ev.preventDefault();
    if (recording) stop(); else start();
  });

  // Until the first `refresh()` answers, the button is off with no claim
  // either way — an unasked question is not a reason.
  btn.disabled = true;
  btn.title = 'Checking the transcription server…';
  hint.hidden = true;

  /** The surface closed: abandon the take, upload nothing, say nothing. */
  function cancel() {
    abandoned = true;
    if (inFlight) inFlight.abort();
    release();
    setHint('');
    setState('');
    if (!busy) btn.disabled = !ready;
  }

  return { refresh: refresh, cancel: cancel };
}
