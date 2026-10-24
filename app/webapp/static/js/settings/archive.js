/* task-os — the batch archiver's half of GET /api/status: where it lives, its
 * threshold and the row's word. */

'use strict';

import { codeEl, pct } from '../../format.js';
import { setWord } from './words.js';

/** The batch archiver's half of `GET /api/status` (#157–#159, #167): where
 *  the archiver lives and its threshold — the two rows of the Email
 *  archiving sheet that archive.js does not draw (its head names the state,
 *  the model and the runs) — and the row's word. Not configured carries its
 *  reason in archive.js's Archiver row; `null` = the status call itself
 *  failed, which is "unknown" and not the same as "off". This module never
 *  follows a live run itself (#262): archive.js does, and publishes each
 *  status it reads back here through `renderArchive` — so "running"
 *  resolves into the run's own counts when its poll finishes. */
export function renderArchive(ctx, st) {
  const rows = [ctx.els.statusArchiveRepo, ctx.els.statusArchiveThreshold];
  rows.forEach(function (el) { el.replaceChildren(); el.classList.remove('muted'); });
  if (!st) {
    rows.forEach(function (el) { el.textContent = 'unknown'; });
    setWord(ctx, ctx.els.archiveCardMeta, 'unknown');
  } else if (!st.configured) {
    rows.forEach(function (el) { el.textContent = '–'; });
    setWord(ctx, ctx.els.archiveCardMeta, 'off');
  } else {
    ctx.els.statusArchiveRepo.append(codeEl(st.repo || 'unknown'));
    ctx.els.statusArchiveThreshold.append(
      pct(st.confidence_threshold),
      ' · ' + (st.candidates == null ? '?' : st.candidates) + ' folder(s) ranked per mail'
    );
    setWord(ctx, ctx.els.archiveCardMeta, archiveWord(st));
  }
  ctx.opts.onHead();
}

/** The row's one word. `agreement` is the only rate the status block
 *  carries, so it is the one reported — an accept rate would be a number
 *  nobody here measures. */
function archiveWord(st) {
  if (st.running) return 'running';
  const last = st.last_run;
  if (st.last_error || (last && last.status === 'failed')) return 'error';
  if (last && last.agreement != null) return pct(last.agreement) + ' agreed';
  return 'on';
}
