/* task-os — Settings → Email archiving: the wording helpers every part shares
 * (counts, folder and path shortening). Pure: no DOM, no state. */

'use strict';

//: An absolute Windows / UNC / POSIX path sitting inside a sentence. Used to
//: fold one out of a reason at phone width, where a 90-character path is the
//: whole card and pushes everything else off the right edge.
const PATH_IN_TEXT = /(?:[A-Za-z]:[\\/]|\\\\)[^\s"'<>|]+|(?:\/[^\s"'<>|/]+){4,}/g;

/** `7 mail(s) · 3 filed · 3 need you · 1 failed`. */
export function counts(r) {
  return (r.planned || 0) + ' mail(s) · ' + outcomes(r);
}

/** What the run did with the mails, without restating how many there were —
 *  the three outcomes add up to the plan. */
export function outcomes(r) {
  return (r.archived || 0) + ' filed · ' + (r.needs_review || 0) + ' need you · '
    + (r.failed || 0) + ' failed';
}

/** The last three components of a folder path — enough to recognise it; the
 *  full path is the title. The archiver reports Windows separators. */
export function shortFolder(path) {
  const parts = String(path || '').split(/[\\/]+/).filter(Boolean);
  return parts.slice(-3).join(' › ') || String(path || '');
}

export function sameFolder(a, b) {
  if (!a || !b) return false;
  const norm = function (p) { return String(p).replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLowerCase(); };
  return norm(a) === norm(b);
}

export function shortenPaths(text) {
  return String(text).replace(PATH_IN_TEXT, function (found) {
    const parts = found.split(/[\\/]+/).filter(Boolean);
    return parts.length > 3 ? '… ' + parts.slice(-3).join(' › ') : found;
  });
}
