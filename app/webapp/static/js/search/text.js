/* task-os — Search: the wording the tab shares. Pure, so the sentences are
 * tested without a browser (tests/test_search_fold.py loads them through
 * search.js, which re-exports `markHtml` and `foldParts`). */

'use strict';

import { escapeHtml } from '../../format.js';

export const KINDS = [
  { kind: 'tasks', label: 'Tasks' },
  { kind: 'folders', label: 'Folders' },
  { kind: 'emails', label: 'Emails' },
  { kind: 'issues', label: 'Issues' },
];
export const HINT = 'Searches your tasks, folders, emails and issues as you type.';

/** `[match]` marks → <mark>, everything else escaped. */
export function markHtml(text) {
  return escapeHtml(text).replace(/\[([^\[\]]+)\]/g, '<mark>$1</mark>');
}

/** "a", "a and b", "a, b and c" — lower-cased kind labels for a sentence. */
function listWords(words) {
  const w = words.map(function (s) { return s.toLowerCase(); });
  return w.length < 2 ? w.join('') : w.slice(0, -1).join(', ') + ' and ' + w[w.length - 1];
}

/**
 * What one folded line says about the kinds without a group (#395). Pure, so
 * the wording is tested without a browser.
 * @param {{none?: string[], hidden?: number, off?: string[]}} fold
 *        none   labels of the kinds that matched nothing (a configured-but-not-
 *               ready kind carries its note: "Folders (index still building)")
 *        hidden task hits the filters or the scope hid
 *        off    labels of the kinds not set up on this install
 * @returns {string[]}  the sentences, joined with " · " on screen; the Settings
 *          link follows the last one when `off` is non-empty
 */
export function foldParts(fold) {
  const parts = [];
  if (fold.none && fold.none.length) parts.push('No matches in ' + listWords(fold.none));
  if (fold.hidden) parts.push(fold.hidden + ' task ' + (fold.hidden === 1 ? 'hit' : 'hits') + ' hidden by the filters or the scope');
  if (fold.off && fold.off.length) parts.push('Not set up: ' + listWords(fold.off));
  return parts;
}

export function hitWord(n) { return n + (n === 1 ? ' hit' : ' hits'); }
