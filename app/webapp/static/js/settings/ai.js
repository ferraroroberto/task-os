/* task-os — the local hub used by staged Inbox triage. */

'use strict';

import { codeEl, fmtTsShort, statusPart } from '../../format.js';
import { setWord } from './words.js';

export function renderAI(ctx, st) {
  ctx.els.statusAI.replaceChildren();
  ctx.els.statusAIModel.replaceChildren();
  ctx.els.statusAI.classList.remove('muted');
  ctx.els.statusAIModel.classList.remove('muted');
  if (!st) {
    ctx.els.statusAI.textContent = 'unknown';
    ctx.els.statusAIModel.textContent = '–';
    setWord(ctx, ctx.els.aiCardMeta, 'unknown');
    return;
  }
  ctx.els.statusAIModel.append(st.model ? codeEl(st.model) : 'not set');
  if (!st.enabled) {
    const label = st.configured ? 'not reachable' : 'off';
    ctx.els.statusAI.append(statusPart('off', label), ' — ' + (st.reason || 'unknown'));
    setWord(ctx, ctx.els.aiCardMeta, st.configured ? 'unavailable' : 'off');
    return;
  }
  ctx.els.statusAI.append(
    statusPart('ok', 'reachable'),
    st.checked_at ? ' · checked ' + fmtTsShort(st.checked_at) : ''
  );
  setWord(ctx, ctx.els.aiCardMeta, 'on');
}
