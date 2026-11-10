/* task-os — the folder opener + folder search card (Step 9): the per-PC install
 * command, and where folder search is answered (folder-explorer). */

'use strict';

import { codeEl, copyText, statusPart } from '../../format.js';

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
    return;
  }
  // The address only: whether it answers is the Search sheet's row, so this status never waits on it.
  dd.append(statusPart('ok', 'on'), ' · answered by folder-explorer at ', codeEl(f.url || ''));
}
