/* task-os — the folder opener + folder index card (Step 9): the per-PC install
 * command and "Reindex folders now". */

'use strict';

import { api } from '../../api.js';
import { codeEl, copyText, fmtTsShort, statusPart } from '../../format.js';
import { toast } from '../../toast.js';

export function renderOpener(ctx, op) {
  const dd = ctx.els.statusOpener;
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!op) { dd.append(statusPart('warn', 'unknown')); return; }
  if (op.installed_here === true) dd.append(statusPart('ok', 'installed on the server PC'));
  else if (op.installed_here === false) dd.append(statusPart('off', 'not installed on the server PC'));
  else dd.append(statusPart('warn', 'unknown on this OS'));
  // Which registration shape is in use is its own state: the fallback hands the
  // URL to a command interpreter as a string, so it must not read as "installed".
  if (op.mode === 'launcher') dd.append(' · ', statusPart('ok', 'launcher mode'));
  else if (op.mode === 'launcher-stale') dd.append(' · ', statusPart('warn', 'launcher mode (old, visible console) — re-run the command below'));
  else if (op.mode === 'fallback') dd.append(' · ', statusPart('warn', 'fallback mode — re-run the command below; see opener/README.md'));
  dd.append(' · other PCs: paste the command below once (this browser asks "Open task-os opener?" the first time)');
  const cmd = (op.install || '').split(op.base_url_token || '<base-url>').join(location.origin);
  ctx.els.openerInstall.textContent = cmd || 'install.txt missing';
  ctx.els.openerUninstall.textContent = op.uninstall || '';
  ctx.els.openerEnv.textContent = op.env_template || '';
  ctx.els.openerCopy.onclick = function () { copyText(cmd, ctx.els.openerCopy); };
  ctx.els.openerEnvCopy.onclick = function () { copyText(op.env_template || '', ctx.els.openerEnvCopy); };
}

export function renderIndexRow(ctx, dd, f) {
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!f || !f.enabled) {
    dd.append(statusPart('off', 'not configured'), ' — ' + ((f && f.reason) || 'unknown'));
    ctx.els.reindexBtn.hidden = true;
    return;
  }
  ctx.els.reindexBtn.hidden = false;
  const roots = (f.roots || []).map(function (r) { return r.ref + (r.exists ? '' : ' (missing)'); }).join(', ');
  dd.append(
    statusPart(f.indexing ? 'warn' : (f.last_error ? 'warn' : 'ok'), f.indexing ? 'indexing…' : (f.last_error ? 'error' : 'indexed')),
    ' · ', codeEl(roots), ' · ' + (f.entries == null ? '?' : f.entries) + ' folder(s)',
    ' · last indexed ' + (f.last_indexed ? fmtTsShort(f.last_indexed) : '–') + (f.stale && f.last_indexed ? ' (stale, >24 h)' : '')
  );
  if (f.last_error) dd.append(' · ' + f.last_error);
}

export function wireReindex(ctx) {
  ctx.els.reindexBtn.addEventListener('click', async function () {
    ctx.els.reindexBtn.disabled = true;
    try {
      const r = await api('/api/folders/reindex', { method: 'POST', body: {} });
      toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success');
    } catch (err) { toast(err.message || 'Reindex failed', 'error'); }
    ctx.els.reindexBtn.disabled = false;
    ctx.refreshStatus();
  });
}
