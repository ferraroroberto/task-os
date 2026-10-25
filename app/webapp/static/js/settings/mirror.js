/* task-os — the markdown mirror and the dated .db copies (Step 6): their status
 * rows and the import-conflict preview with its Clear action. */

'use strict';

import { api } from '../../api.js';
import { codeEl, fmtTsShort, statusPart } from '../../format.js';
import { toast } from '../../toast.js';

export function renderMirrorRow(dd, m) {
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!m || !m.enabled) {
    dd.append(statusPart('off', 'not configured'), ' — ' + ((m && m.reason) || 'unknown'));
    return;
  }
  dd.append(
    statusPart(m.errors ? 'warn' : 'ok', m.errors ? 'enabled · ' + m.errors + ' file(s) skipped' : 'enabled'),
    ' · ', codeEl(m.dir), ' · ' + (m.files == null ? '?' : m.files) + ' file(s)',
    ' · last export ' + (m.last_export ? fmtTsShort(m.last_export) : '–'),
    ' · last import ' + (m.last_import ? fmtTsShort(m.last_import) : '–')
  );
  if (m.error_files && m.error_files.length) dd.append(' · skipped: ' + m.error_files.join(', '));
}

// Mirror import diagnostics — recorded as `mirror_events` rows,
// never as a comment on the task; this row is the "visible at app level"
// half of the fix, with an inline preview (inspect) and a Clear action.
export async function renderMirrorEventsRow(ctx, m) {
  const dd = ctx.els.statusMirrorEvents;
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!m || !m.enabled) {
    dd.append(statusPart('off', 'not configured'));
    ctx.els.mirrorEventsClear.hidden = true;
    return;
  }
  const n = m.events || 0;
  if (!n) {
    dd.append(statusPart('ok', 'none since the last review'));
    ctx.els.mirrorEventsClear.hidden = true;
    return;
  }
  dd.append(statusPart('warn', n + ' since the last review'));
  ctx.els.mirrorEventsClear.hidden = false;
  try {
    const r = await api('/api/mirror/events');
    const items = (r.events || []).slice(0, 3).map(function (e) {
      return e.field + ': file said ' + e.file_value + ', kept ' + e.kept_value;
    });
    if (items.length) dd.append(' — ' + items.join('; ') + (n > items.length ? '; +' + (n - items.length) + ' more' : ''));
  } catch (_) { /* the count above still stands */ }
}

export function wireMirrorEventsClear(ctx) {
  ctx.els.mirrorEventsClear.addEventListener('click', async function () {
    ctx.els.mirrorEventsClear.disabled = true;
    try {
      const r = await api('/api/mirror/events', { method: 'DELETE' });
      toast('Cleared ' + r.cleared + ' import conflict(s)', 'success');
    } catch (err) { toast(err.message || 'Clear failed', 'error'); }
    ctx.els.mirrorEventsClear.disabled = false;
    ctx.refreshStatus();
  });
}

export function renderBackupRow(dd, b) {
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!b || !b.enabled) {
    dd.append(statusPart('off', 'not configured'), ' — ' + ((b && b.reason) || 'unknown'));
    return;
  }
  dd.append(
    statusPart(b.last_error ? 'warn' : 'ok', b.last_error ? 'error' : 'enabled'),
    ' · ', codeEl(b.dir), ' · last ' + (b.last_file || '–'), ' · next ' + (b.next_run ? fmtTsShort(b.next_run) : '–')
  );
  if (b.last_error) dd.append(' · ' + b.last_error);
}
