/* task-os — the header: the title naming the view on screen and the line
 * beside it. Each function takes the app composer's `app` first.
 */

'use strict';

import { HEAD_MAX_PARTS } from '../../_vendored/home-head/home-head.js';
import { boardHeadParts } from '../../board.js';
import { headLine } from '../../today.js';

// ------------------------------------------------------------ the header
/** The header names the view on screen: the vendored home-head's
 *  title is each pane's heading, so every tab opens with one. */
export function setHeadTitle(app, text, iconId) {
  app.els.homeTitleText.textContent = text;
  app.els.homeTitleIcon.setAttribute('href', '#' + iconId);
}

/** The line beside the title names an exception or states a plain fact
 *  (design.md `page-header`). On Today: `headLine` over the counts of
 *  the horizons Today just drew, so the header and the list never disagree —
 *  one text node in one tone (`.status.is-attention`), never per-part spans:
 *  Today's line is always a single sentence, and splitting it across spans
 *  measurably shifts the browser's text shaping at the
 *  word boundary — a sub-pixel kerning drift the screenshot gallery caught
 *  that no eye would. On the Board: `boardHeadParts` over the counts its
 *  lanes were drawn from — Inbox arrivals in the accent, *ahead of* overdue /
 *  due today. On Settings: the mails the last archiving run left for
 *  you, ahead of a failing service even in the danger tone — "needs
 *  you" matters more than severity. Both orderings put importance ahead of
 *  severity, which the vendored renderer's `TONE_RANK` (danger, then
 *  attention — nothing else ranked) cannot reproduce: handing it these two
 *  arrays would have it silently re-sort them by severity and lose that
 *  ordering. So Board and Settings paint their own two parts locally
 *  (`paintParts` below) — sharing the vendored `.head-exception` markup/CSS
 *  and its `HEAD_MAX_PARTS` cap, short of the one piece that needs
 *  project-scaffolding's say: ranking by the caller's own importance, not
 *  just severity (and an 'accent' entry in `TONE_RANK` for the Board's own
 *  case). The open count is not repeated here: it is the filter field's
 *  placeholder. The other views name their own exceptions in their redesign
 *  steps; until then their line is empty rather than a count. */
export function renderHeadStatus(app) {
  const el = app.els.homeHeadStatus;
  let text = '';
  let attention = false;
  let parts = null;
  const onPane = !app.state.settingsOpen && !app.state.journal.open;
  if (app.state.headNote) text = app.state.headNote;
  else if (app.state.tab === 'today' && onPane && app.state.todayCounts) {
    const line = headLine(app.state.todayCounts);
    text = line.text;
    attention = line.attention;
  } else if (app.state.tab === 'board' && onPane && app.state.boardCounts) {
    parts = boardHeadParts(app.state.boardCounts);
  } else if (app.state.tab === 'time' && onPane && app.time) {
    text = app.time.headText();
  } else if (app.state.settingsOpen) {
    parts = app.settingsHeadParts();
  }
  el.classList.toggle('is-attention', attention);
  if (!parts) { el.textContent = text; return; }
  paintParts(el, parts);
}

/** Paint an already-ordered, already-capped `{text, tone}[]` with the
 *  vendored home-head markup (`.head-exception[data-tone]`) but without its
 *  tone-ranked sort — see `renderHeadStatus` above for why Board and Settings
 *  cannot use the vendored sort itself. */
function paintParts(el, parts) {
  if (!parts.length) { el.textContent = ''; delete el.dataset.tone; return; }
  el.replaceChildren();
  parts.forEach(function (part, i) {
    if (i) el.append(' · ');
    const span = document.createElement('span');
    span.className = 'head-exception';
    span.dataset.tone = part.tone;
    span.textContent = part.text;
    el.appendChild(span);
  });
}

/** The Settings line's parts: the archive's "needs you" first — the
 *  one exception that asks for a hand rather than a fix — then settings.js's
 *  own (failing services, or the plain count), at most `HEAD_MAX_PARTS`. */
export function settingsHeadParts(app) {
  const own = app.settings.headParts();
  const needs = app.archiveNeedsYou();
  if (!needs) return own;
  // An exception line names exceptions only: the plain count yields to it.
  return [{ text: needs + (needs === 1 ? ' mail needs' : ' mails need') + ' you', tone: 'attention' }]
    .concat(own.filter(function (p) { return p.tone !== 'muted'; })).slice(0, HEAD_MAX_PARTS);
}

/** …a tab's name and glyph, read off its own nav button (one source). */
export function setHeadTitleFromTab(app, tab) {
  const btn = document.querySelector('nav.tabs .tab[data-tab="' + tab + '"]');
  if (!btn) return;
  app.setHeadTitle(btn.querySelector('.tab-label').textContent, btn.querySelector('use').getAttribute('href').slice(1));
}
