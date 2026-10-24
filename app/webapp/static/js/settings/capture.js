/* task-os — the flagged-email poller (#98): its status rows and "Check now". */

'use strict';

import { api } from '../../api.js';
import { fmtTsShort, statusPart } from '../../format.js';
import { toast } from '../../toast.js';
import { setWord } from './words.js';

/** The flagged-email poller's half of `GET /api/status` (#98). Off always
 *  carries its reason — an unconfigured channel is a visible state, not a
 *  quiet nothing. `null` = the status call itself failed. */
export function renderCapture(ctx, st) {
  ctx.els.captureRunNow.disabled = !(st && st.enabled);
  ctx.els.statusCapture.replaceChildren();
  ctx.els.statusCaptureRun.replaceChildren();
  ctx.els.statusCapture.classList.remove('muted');
  ctx.els.statusCaptureRun.classList.remove('muted');
  if (!st) {
    ctx.els.statusCapture.textContent = 'unknown';
    ctx.els.statusCaptureRun.textContent = '–';
    setWord(ctx, ctx.els.captureCardMeta, 'unknown');
    return;
  }
  if (!st.enabled) {
    ctx.els.statusCapture.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
    ctx.els.statusCaptureRun.textContent = '–';
    setWord(ctx, ctx.els.captureCardMeta, 'off');
    return;
  }
  ctx.els.statusCapture.append(
    statusPart(st.last_error ? 'warn' : 'ok', st.last_error ? 'error' : 'enabled'),
    ' · every ' + st.poll_minutes + ' min',
    st.next_run ? ' · next ' + fmtTsShort(st.next_run) : ''
  );
  if (st.last_error) ctx.els.statusCapture.append(' · ' + st.last_error);
  const r = st.last_result;
  if (!st.last_run) {
    ctx.els.statusCaptureRun.textContent = 'not yet';
  } else {
    ctx.els.statusCaptureRun.append(fmtTsShort(st.last_run));
    if (r) {
      ctx.els.statusCaptureRun.append(
        ' · ' + r.listed + ' flagged · ' + r.created + ' new'
        + (r.dismissed ? ' · ' + r.dismissed + ' dismissed' : '')
        + (r.errors && r.errors.length ? ' · ' + r.errors.length + ' error(s)' : '')
      );
    }
  }
  setWord(ctx, ctx.els.captureCardMeta, st.last_error ? 'error' : (st.last_run ? 'checked' : 'on'));
}

export function wireCaptureRunNow(ctx) {
  ctx.els.captureRunNow.addEventListener('click', async function () {
    ctx.els.captureRunNow.disabled = true;
    try {
      const r = await api('/api/capture/email/run', { method: 'POST', body: {} });
      toast('Capture: ' + r.listed + ' flagged · ' + r.created + ' new task(s)', 'success');
      if (r.created) ctx.opts.onCaptured();
    } catch (err) { toast(err.message || 'Capture failed', 'error'); }
    ctx.els.captureRunNow.disabled = false;
    ctx.refreshStatus();
  });
}
