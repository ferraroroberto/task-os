/* task-os — which of the four indexes this install can query (Step 10). */

'use strict';

import { api } from '../../api.js';
import { statusPart } from '../../format.js';
import { setWord } from './words.js';

const SEARCH_KIND_ROWS = { tasks: 'statusSearchTasks', folders: 'statusSearchFolders', emails: 'statusSearchEmails', issues: 'statusSearchIssues' };

/** Which indexes this install can query (GET /api/search/status). */
export async function refreshSearchStatus(ctx) {
  let adapters = null;
  try { adapters = (await api('/api/search/status')).adapters || []; } catch (err) { adapters = null; }
  let on = 0;
  Object.keys(SEARCH_KIND_ROWS).forEach(function (kind) {
    const dd = document.getElementById(SEARCH_KIND_ROWS[kind]);
    dd.replaceChildren();
    dd.classList.remove('muted');
    const a = adapters && adapters.find(function (x) { return x.kind === kind; });
    if (!adapters) { dd.append(statusPart('warn', 'unknown')); return; }
    if (a && a.configured) {
      on += 1;
      dd.append(statusPart('ok', 'indexed'));
      if (a.note) dd.append(' · ' + a.note);
    } else {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((a && a.reason) || 'unknown'));
    }
  });
  setWord(ctx, ctx.els.searchCardMeta, adapters ? (on ? 'indexed' : 'off') : 'unknown');
  ctx.opts.onHead();
  ctx.opts.onSearchStatus();
}
