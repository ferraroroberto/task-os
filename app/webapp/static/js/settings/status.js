/* task-os — ONE GET /api/status feeds the access, mirror/backup, opener,
 * capture, archive, calendar, voice and AI rows. An unreachable endpoint is its
 * own visible state — "unknown — <reason>" — never a stale "Loading…". */

'use strict';

import { api } from '../../api.js';
import { renderAccessCard, renderAccessUnknown } from './access.js';
import { renderAI } from './ai.js';
import { renderArchive } from './archive.js';
import { renderCalendar } from './calendar.js';
import { renderCapture } from './capture.js';
import { renderIndexRow, renderOpener } from './folders.js';
import { renderBackupRow, renderMirrorEventsRow, renderMirrorRow } from './mirror.js';
import { renderEnrich, renderVoice } from './voice.js';
import { setWord } from './words.js';

// One GET /api/status feeds the Settings pane's Phone access card (https +
// auth, Step 7), the mirror / backup card (Step 6) and the opener card (Step 9).
// The card headers carry a state word (on · synced · indexed · off), never a count.
export async function refreshStatus(ctx) {
  try {
    const [body, team, me] = await Promise.all([
      api('/api/status'),
      api('/api/team').catch(function (err) { return err; }),
      api('/api/me').catch(function (err) { return err; }),
    ]);
    renderAccessCard(ctx, body, team, me);
    renderMirrorRow(ctx.els.statusMirror, body.mirror);
    renderBackupRow(ctx.els.statusBackup, body.backup);
    renderMirrorEventsRow(ctx, body.mirror).catch(function () {});
    ctx.statusFailed = false;
    const on = [body.mirror && body.mirror.enabled, body.backup && body.backup.enabled].filter(Boolean).length;
    // A backup that failed is the row's word, whatever else is on (the
    // header names it, "Backup failing").
    setWord(ctx, ctx.els.mirrorCardMeta, body.backup && body.backup.last_error ? 'error'
      : on === 2 ? 'both on' : on === 1 ? 'one of two on' : 'off');
    renderOpener(ctx, body.opener);
    renderIndexRow(ctx, ctx.els.statusIndex, body.folders);
    const f = body.folders;
    setWord(ctx, ctx.els.folderCardMeta, f && f.enabled ? (f.indexing ? 'indexing' : (f.last_error ? 'error' : 'indexed')) : 'index off');
    renderCapture(ctx, body.capture);
    renderArchive(ctx, body.archive);
    // A run this page did not start (another device): hand it to the Archive
    // pane, which follows it and publishes the outcome back.
    if (body.archive && body.archive.running) ctx.opts.onArchiveRun();
    renderCalendar(ctx, body.calendar);
    renderVoice(ctx, body.voice);
    renderEnrich(ctx, body.enrich);
    renderAI(ctx, body.ai);
  } catch (err) {
    // An unreachable status is its own visible state, never a stale "Loading…".
    ctx.statusFailed = true;
    renderAccessUnknown(ctx, err.message);
    ctx.els.statusMirror.textContent = 'unknown — ' + err.message;
    ctx.els.statusBackup.textContent = 'unknown — ' + err.message;
    ctx.els.statusMirrorEvents.textContent = 'unknown — ' + err.message;
    setWord(ctx, ctx.els.mirrorCardMeta, 'unknown');
    ctx.els.statusOpener.textContent = 'unknown — ' + err.message;
    ctx.els.statusIndex.textContent = 'unknown — ' + err.message;
    setWord(ctx, ctx.els.folderCardMeta, 'unknown');
    renderCapture(ctx, null);
    renderArchive(ctx, null);
    renderCalendar(ctx, null);
    renderVoice(ctx, null);
    renderEnrich(ctx, null);
    renderAI(ctx, null);
  }
  ctx.opts.onHead();
}
