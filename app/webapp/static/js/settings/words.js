/* task-os — the state word each service row shows, and the Settings header
 * line read from them (design.md `page-header`). `ctx.words` holds the word by
 * its value element's id; `ctx.statusFailed` is the last GET /api/status
 * failing: one "unknown", not nine. */

'use strict';

import { HEAD_MAX_PARTS } from '../../_vendored/home-head/home-head.js';

//: A row's state word that is an exception, and its tone (design.md's status
//: chip tone map): broken is danger, needs-a-look is attention. Every other
//: word — on, synced, off, … — is a plain fact in the muted value colour.
export const WORD_TONES = { error: 'danger', stale: 'attention', unknown: 'attention', unavailable: 'attention' };
//: The service rows, by their value element, and the name the header line
//: gives each when it is the exception ("Issue sync failing").
export const SERVICE_NAMES = {
  issuesCardMeta: 'Issue sync', calendarCardMeta: 'Calendar', captureCardMeta: 'Capture',
  archiveCardMeta: 'Archiving', searchCardMeta: 'Search', folderCardMeta: 'Folder index',
  voiceCardMeta: 'Voice', aiCardMeta: 'AI triage', mirrorCardMeta: 'Backup',
};
//: The words that say a service is not on (the rest of the header's plain count).
export const OFF_WORDS = ['off', 'index off', 'unknown'];

/** A row's state word, in its tone when it is an exception. */
export function setWord(ctx, el, word) {
  el.textContent = word;
  const tone = WORD_TONES[word];
  if (tone) el.dataset.tone = tone;
  else delete el.dataset.tone;
  ctx.words[el.id] = word;
}

/** The Settings header's line (design.md `page-header`, #397): the services
 *  in an exception tone, broken first, at most two; else the plain count of
 *  the services that are on. Empty until a status has been read. */
export function headParts(ctx) {
  if (ctx.statusFailed) return [{ text: 'Status unknown', tone: 'attention' }];
  const ids = Object.keys(SERVICE_NAMES).filter(function (id) { return id in ctx.words; });
  if (!ids.length) return [];
  const verbs = { error: 'failing', stale: 'stale', unknown: 'unknown', unavailable: 'unreachable' };
  const parts = [];
  ['danger', 'attention'].forEach(function (tone) {
    ids.forEach(function (id) {
      if (WORD_TONES[ctx.words[id]] === tone) parts.push({ text: SERVICE_NAMES[id] + ' ' + verbs[ctx.words[id]], tone: tone });
    });
  });
  if (parts.length) return parts.slice(0, HEAD_MAX_PARTS);
  const on = ids.filter(function (id) { return OFF_WORDS.indexOf(ctx.words[id]) < 0; }).length;
  return [{ text: on + ' of ' + ids.length + ' services on', tone: 'muted' }];
}
