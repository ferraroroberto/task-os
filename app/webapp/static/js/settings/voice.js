/* task-os — the transcription endpoint (#92) and the light model that turns a
 * spoken sentence into a title and a description (#147). */

'use strict';

import { codeEl, fmtTsShort, statusPart } from '../../format.js';
import { setWord } from './words.js';

/** The whisper endpoint's half of `GET /api/status` (#92). Unreachable
 *  always carries its reason — the same sentence the quick-add mic's hint
 *  shows. `null` = the status call itself failed, which is "not
 *  established", not "off". */
export function renderVoice(ctx, st) {
  ctx.els.statusVoice.replaceChildren();
  ctx.els.statusVoiceUrl.replaceChildren();
  ctx.els.statusVoice.classList.remove('muted');
  ctx.els.statusVoiceUrl.classList.remove('muted');
  if (!st) {
    ctx.els.statusVoice.textContent = 'unknown';
    ctx.els.statusVoiceUrl.textContent = '–';
    setWord(ctx, ctx.els.voiceCardMeta, 'unknown');
    return;
  }
  ctx.els.statusVoiceUrl.append(st.url ? codeEl(st.url) : 'not set');
  if (!st.enabled) {
    ctx.els.statusVoice.append(statusPart('off', 'not reachable'), ' — ' + (st.reason || 'unknown'));
    setWord(ctx, ctx.els.voiceCardMeta, 'off');
    return;
  }
  // Which endpoint answered matters: the hub means the fleet's transcribe
  // role (parakeet first), the fallback means the local CPU whisper server.
  const serving = { hub: 'hub', fallback: 'local whisper (fallback)' }[st.serving] || 'unknown';
  // The live-transcript cadence (#146). Absent is not "off": the install
  // did not say, and saying "off" for it would be a claim nobody made.
  const every = st.partial_interval_seconds;
  const live = typeof every !== 'number' ? 'live transcript unknown'
    : every > 0 ? 'live every ' + (+every.toFixed(2)) + 's'
      : 'live transcript off';
  ctx.els.statusVoice.append(
    statusPart('ok', 'reachable'),
    ' · ' + serving,
    ' · ' + live,
    st.checked_at ? ' · checked ' + fmtTsShort(st.checked_at) : ''
  );
  setWord(ctx, ctx.els.voiceCardMeta, st.serving === 'fallback' ? 'fallback' : 'on');
}

/** The light model that turns a spoken sentence into a title and a
 *  description (#147). Off is a state with a reason, not a blank: a
 *  spoken line still becomes a task, it just keeps the deterministic
 *  parse — and this row is where you find that out. */
export function renderEnrich(ctx, st) {
  ctx.els.statusEnrich.replaceChildren();
  ctx.els.statusEnrich.classList.remove('muted');
  if (!st) { ctx.els.statusEnrich.textContent = 'unknown'; return; }
  if (!st.enabled) {
    ctx.els.statusEnrich.append(statusPart('off', 'not reachable'),
      ' — ' + (st.reason || 'unknown') + ' · the spoken line keeps the plain parse');
    return;
  }
  ctx.els.statusEnrich.append(statusPart('ok', 'reachable'), ' · ', codeEl(st.model || 'unknown'));
}
