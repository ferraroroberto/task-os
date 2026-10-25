/* task-os — quick-add: the mic beside line 1. Dictation writes into line 1
 * *after* whatever was already typed, so pressing the mic mid-thought adds to
 * the line instead of eating it. The prefix is fixed at the moment recording
 * starts; every partial and the final transcript replace only the part after
 * it. */

'use strict';

import { api } from '../../api.js';
import { toast } from '../../toast.js';
import { mountMic } from '../../voice.js';
import { applyParse, parseNow } from './preview.js';

function renderSpoken(ctx, text, provisional) {
  const { input, submit } = ctx.els;
  const prefix = ctx.st.spokenPrefix;
  const sep = prefix && !/\s$/.test(prefix) ? ' ' : '';
  const line = prefix + (text ? sep + text : '');
  input.value = line;
  submit.disabled = !line.trim();
  input.classList.toggle('is-dictating', !!provisional);
  return line;
}

// The final transcript brings its own parse with it — the route returns
// both, so a spoken line costs one round trip, not two. Partials carry no
// parse on purpose: a due date appearing and moving while the sentence is
// still landing is noise, so the chips and dates wait for the end.
// The model may replace the title and fill the description; the dates it
// proposes are resolved server-side from phrases it had to quote out of
// the transcript, so a date it invented cannot reach the form. Every
// failure is reported as `source: "parser"` and simply leaves the
// deterministic answer standing — losing a tidy-up must not look like a
// broken microphone.
async function enrich(ctx, text) {
  const { input, submit, desc } = ctx.els;
  const st = ctx.st;
  const my = ++st.enrichSeq;
  input.classList.add('is-enriching');
  try {
    const res = await api('/api/enrich', { method: 'POST', body: { text: text } });
    if (my !== st.enrichSeq || !ctx.dialog.open) return;
    if (res.source !== 'llm' || !res.title) return;   // the parser's answer stands
    input.value = res.title;
    submit.disabled = !res.title.trim();
    // Only ever *fills* the description, never overwrites one you typed.
    if (res.description && !desc.value.trim()) desc.value = res.description;
    st.seq++;                           // this line is not what /api/parse saw
    applyParse(ctx, res, res.title);
  } catch (_) {
    // The route answers 200 even when the model could not be reached, so
    // this is a genuinely broken request — and still not worth a toast:
    // the transcript and its parse are already on the line.
  } finally {
    if (my === st.enrichSeq) input.classList.remove('is-enriching');
  }
}

export function mountDictation(ctx) {
  const { input, mic, voiceHint } = ctx.els;
  const st = ctx.st;
  return mountMic(mic, voiceHint, {
    onStart: function () {
      st.spokenPrefix = input.value;
      window.clearTimeout(st.timer);
      st.seq++;                         // supersede any parse still in flight
    },
    onPartial: function (text) { renderSpoken(ctx, text, true); },
    onResult: function (r) {
      const line = renderSpoken(ctx, r.text, false);
      st.seq++;                         // …and any that started during the take
      // The parse that rode back describes the *transcript*. That is the whole
      // line only when nothing was typed before the mic was pressed; with a
      // prefix it describes a fragment, so the line is re-parsed rather than
      // labelled with an answer to a different question.
      if (line === r.text) applyParse(ctx, r.parse, line);
      else parseNow(ctx);
      input.focus();
      // …and then, only for a spoken line, ask the hub's light model to make
      // a title and a description of the sentence. Deliberately a
      // second round trip rather than folded into /api/transcribe: the
      // transcript and its parse are on screen *now*, and the tidy-up is
      // worth ~1.5 s of waiting only because nothing is waiting on it.
      enrich(ctx, line);
    },
    onError: function (message) {
      input.classList.remove('is-dictating');
      toast(message, 'error');
    },
    // Closing the dialog mid-recording abandons it: nothing is uploaded and
    // no transcript arrives late into a dialog that is no longer open.
    isLive: function () { return ctx.dialog.open; },
  });
}
