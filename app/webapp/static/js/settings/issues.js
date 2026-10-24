/* task-os — the issue provider's status (Step 8) and "Sync now". */

'use strict';

import { codeEl, fmtTsShort, statusPart } from '../../format.js';
import { setWord } from './words.js';

/** The Settings row's half of the issue-provider status; the sync call
 *  itself stays with the bootstrap (the drawer and the palette make it too). */
export function renderIssues(ctx, st) {
  drawIssues(ctx, st);
  ctx.opts.onHead();
}

function drawIssues(ctx, st) {
  const configured = !!(st && st.enabled);
  ctx.els.issuesSyncNow.disabled = !configured;
  ctx.els.statusIssues.replaceChildren();
  ctx.els.statusIssuesSync.replaceChildren();
  ctx.els.statusIssues.classList.remove('muted');
  ctx.els.statusIssuesSync.classList.remove('muted');
  if (!st) {
    ctx.els.statusIssues.textContent = 'unknown';
    ctx.els.statusIssuesSync.textContent = '–';
    setWord(ctx, ctx.els.issuesCardMeta, 'unknown');
    return;
  }
  if (!configured) {
    ctx.els.statusIssues.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
    ctx.els.statusIssuesSync.textContent = '–';
    setWord(ctx, ctx.els.issuesCardMeta, 'off');
    return;
  }
  ctx.els.statusIssues.append(
    statusPart(st.last_error ? 'warn' : 'ok', st.last_error ? 'error' : 'enabled'),
    ' · ', codeEl(st.provider), ' · every ' + st.sync_minutes + ' min',
    st.next_run ? ' · next ' + fmtTsShort(st.next_run) : ''
  );
  if (st.last_error) ctx.els.statusIssues.append(' · ' + (st.last_error_code ? st.last_error_code + ': ' : '') + st.last_error);
  const r = st.last_result;
  if (!st.last_sync) {
    ctx.els.statusIssuesSync.textContent = 'not yet';
  } else {
    ctx.els.statusIssuesSync.append(fmtTsShort(st.last_sync));
    if (r) {
      ctx.els.statusIssuesSync.append(' · ' + r.listed + ' open issue(s) · ' + r.created + ' new · ' + r.retitled + ' retitled · ' + r.reopened + ' reopened · ' + r.closed + ' closed' + (r.errors && r.errors.length ? ' · ' + r.errors.length + ' error(s)' : ''));
    }
  }
  if (st.repos && st.repos.length) ctx.els.statusIssuesSync.append(' · repos: ' + st.repos.join(', '));
  setWord(ctx, ctx.els.issuesCardMeta, st.last_error ? 'error' : (st.last_sync ? 'synced' : 'on'));
}

export function wireIssueSyncNow(ctx) {
  ctx.els.issuesSyncNow.addEventListener('click', function () {
    // the button is the app's one sync control now (#301): it spins while the pass runs
    ctx.els.issuesSyncNow.classList.add('is-busy');
    ctx.opts.onSyncIssues().catch(function () {}).finally(function () { ctx.els.issuesSyncNow.classList.remove('is-busy'); });
  });
}
