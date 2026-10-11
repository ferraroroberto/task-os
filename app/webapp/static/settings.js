/* task-os — the Settings pane: what this install is and what it can reach.
 *
 * One module per view, like Board · Today · Search:
 * `mountSettings(opts)` looks up the pane's rows and sheets once, wires their
 * controls and returns the handle the bootstrap calls when something it owns
 * changes. The pane is five inset groups (#397, design.md `settings group`):
 * each row carries its state word — on · synced · indexed · off, in its tone
 * when it is an exception — and a chevron to its sheet (#settingsSheet), which
 * holds the card the row replaced, under the same ids. One sheet is up at a
 * time and the URL says which (`#settings/<key>`), so the bootstrap opens and
 * closes it (`showSheet` / `hideSheet`) and this module only asks
 * (`opts.onOpenSheet` / `opts.onCloseSheet`). Text size is changed in place.
 *
 *   Row actions    what each touch swipe on a task row runs and what the
 *                  row's ⋯ menu lists, in order (#311) — per device, from the
 *                  one action table; `opts.onRowActions` redraws the rows.
 *   Phone access   https + auth (Step 7) — how this connection came in and
 *                  what the install accepts; "Sign out on this device".
 *   Mirror/backup  the markdown mirror and the dated .db copies (Step 6).
 *   Issues         the issue provider's status (Step 8) + "Sync now". The
 *                  sync itself belongs to the bootstrap (the header ↻, the
 *                  drawer and the palette funnel through the same call), so
 *                  it arrives as `opts.onSyncIssues` and the status arrives
 *                  through `renderIssues(status)`.
 *   Capture        the flagged-email poller (#98) + "Check now". Unlike the
 *                  issue sync this card owns its own call, because nothing
 *                  else in the app triggers a capture pass.
 *   Archive        the batch archiver (#157–#159): where it lives and its
 *                  threshold. The rest of its sheet — the run, the report and
 *                  every review action — is archive.js's (a tab until #397).
 *   Calendar       the Today lane's private ICS feed (#96): its state (off ·
 *                  ok · address refused · unreachable · timed out · not a
 *                  calendar), the host it reads from — never the address —
 *                  and "Refresh now". The refresh answers the fresh group,
 *                  which the bootstrap pushes into Today (`opts.onCalendar`).
 *   Voice          whether a transcription endpoint is answering, and which
 *                  one (#92, #144: the hub — so parakeet — or the local
 *                  whisper fallback). The same status the quick-add mic
 *                  reads. No button: there is nothing to run on demand, only
 *                  somewhere to be up.
 *   AI             whether the local hub used by staged Inbox triage is
 *                  enabled and reachable, plus the configured model (#95).
 *   Search         which of the four indexes this install can query (Step 10);
 *                  the Search tab's own idle view is refreshed through
 *                  `opts.onSearchStatus`.
 *   Folder opener  the per-PC opener install command + the folder index
 *                  (Step 9), with "Reindex folders now".
 *
 * ONE `GET /api/status` feeds the access, mirror/backup, opener, capture, archive, calendar, voice and AI cards
 * (`refreshStatus()`); the search card has its own `GET /api/search/status`
 * (`refreshSearchStatus()`). An unreachable endpoint is its own visible
 * state — "unknown — <reason>" — never a stale "Loading…".
 *
 * The rows' words are the Settings header's line too (`headParts()`, #397):
 * the exceptions among them, else how many services are on.
 */

'use strict';

import { ACTIONS, actionById } from './actions.js';
import { api } from './api.js';
import { codeEl, copyText, fmtTsShort, pct, statusPart } from './format.js';
import { toast } from './toast.js';
import { isDefault, rowPrefs, setRowPrefs } from './rowprefs.js';
import { icon } from './_vendored/icons/icons.js';
import { bindTextSize } from './_vendored/text-size/text-size.js';

const SEARCH_KIND_ROWS = { tasks: 'statusSearchTasks', folders: 'statusSearchFolders', emails: 'statusSearchEmails', issues: 'statusSearchIssues' };

//: A row's state word that is an exception, and its tone (design.md's status
//: chip tone map): broken is danger, needs-a-look is attention. Every other
//: word — on, synced, off, … — is a plain fact in the muted value colour.
const WORD_TONES = { error: 'danger', stale: 'attention', unknown: 'attention', unavailable: 'attention' };
//: The service rows, by their value element, and the name the header line
//: gives each when it is the exception ("Issue sync failing").
const SERVICE_NAMES = {
  issuesCardMeta: 'Issue sync', calendarCardMeta: 'Calendar', captureCardMeta: 'Capture',
  archiveCardMeta: 'Archiving', searchCardMeta: 'Search', folderCardMeta: 'Folder index',
  voiceCardMeta: 'Voice', aiCardMeta: 'AI triage', mirrorCardMeta: 'Backup',
};
//: The words that say a service is not on (the rest of the header's plain count).
const OFF_WORDS = ['off', 'index off', 'unknown'];

/**
 * Wire the Settings pane once and hand back the bootstrap's handle.
 * @param {{onSyncIssues: () => Promise<any>, onSearchStatus: () => void,
 *          onOpenPalette: () => void, onRowActions?: () => void,
 *          onCaptured: () => void, onArchiveRun: () => void,
 *          onCalendar: (group: object) => void, onHead: () => void,
 *          onOpenSheet: (key: string) => void, onCloseSheet: () => void}} opts
 * @returns {{refreshStatus: () => Promise<void>, refreshSearchStatus: () => Promise<void>,
 *            renderArchive: (st: object|null) => void,
 *            renderIssues: (status: object|null) => void,
 *            showSheet: (key: string) => boolean, hideSheet: () => void,
 *            currentSheet: () => (string|null),
 *            headParts: () => Array<{text: string, tone: string}>}}
 */
export function mountSettings(opts) {
  const els = {
    pane: document.getElementById('paneSettings'),
    sheet: document.getElementById('settingsSheet'),
    sheetTitle: document.getElementById('settingsSheetTitle'),
    accessClient: document.getElementById('accessClient'),
    accessRows: document.getElementById('accessRows'),
    signOutBtn: document.getElementById('signOutBtn'),
    mirrorCardMeta: document.getElementById('mirrorCardMeta'),
    statusMirror: document.getElementById('statusMirror'),
    statusBackup: document.getElementById('statusBackup'),
    statusMirrorEvents: document.getElementById('statusMirrorEvents'),
    mirrorEventsClear: document.getElementById('mirrorEventsClear'),
    folderCardMeta: document.getElementById('folderCardMeta'),
    statusOpener: document.getElementById('statusOpener'),
    statusIndex: document.getElementById('statusIndex'),
    openerInstall: document.getElementById('openerInstall'),
    openerCopy: document.getElementById('openerCopy'),
    openerUninstall: document.getElementById('openerUninstall'),
    openerEnv: document.getElementById('openerEnv'),
    openerEnvCopy: document.getElementById('openerEnvCopy'),
    reindexBtn: document.getElementById('reindexBtn'),
    issuesCardMeta: document.getElementById('issuesCardMeta'),
    statusIssues: document.getElementById('statusIssues'),
    statusIssuesSync: document.getElementById('statusIssuesSync'),
    issuesSyncNow: document.getElementById('issuesSyncNow'),
    paletteOpen: document.getElementById('paletteOpen'),
    textSizeControl: document.getElementById('textSizeControl'),
    rowActionsMeta: document.getElementById('rowActionsMeta'),
    swipeRight: document.getElementById('swipeRightSelect'),
    swipeLeft: document.getElementById('swipeLeftSelect'),
    rowMenuList: document.getElementById('rowMenuList'),
    rowActionsReset: document.getElementById('rowActionsReset'),
    captureCardMeta: document.getElementById('captureCardMeta'),
    statusCapture: document.getElementById('statusCapture'),
    statusCaptureRun: document.getElementById('statusCaptureRun'),
    captureRunNow: document.getElementById('captureRunNow'),
    archiveCardMeta: document.getElementById('archiveCardMeta'),
    statusArchiveRepo: document.getElementById('statusArchiveRepo'),
    statusArchiveThreshold: document.getElementById('statusArchiveThreshold'),
    calendarCardMeta: document.getElementById('calendarCardMeta'),
    statusCalendar: document.getElementById('statusCalendar'),
    statusCalendarSource: document.getElementById('statusCalendarSource'),
    statusCalendarFetched: document.getElementById('statusCalendarFetched'),
    calendarRefresh: document.getElementById('calendarRefresh'),
    voiceCardMeta: document.getElementById('voiceCardMeta'),
    statusVoice: document.getElementById('statusVoice'),
    statusVoiceUrl: document.getElementById('statusVoiceUrl'),
    statusEnrich: document.getElementById('statusEnrich'),
    aiCardMeta: document.getElementById('aiCardMeta'),
    statusAI: document.getElementById('statusAI'),
    statusAIModel: document.getElementById('statusAIModel'),
    searchCardMeta: document.getElementById('searchCardMeta'),
  };

  // ------------------------------------------------------- row values
  // The state word each service row shows, by its value element's id — what
  // the header line is read from (`headParts`).
  const words = {};
  let statusFailed = false;   // the last GET /api/status failed: one "unknown", not nine

  /** A row's state word, in its tone when it is an exception. */
  function setWord(el, word) {
    el.textContent = word;
    const tone = WORD_TONES[word];
    if (tone) el.dataset.tone = tone;
    else delete el.dataset.tone;
    words[el.id] = word;
  }

  /** The Settings header's line (design.md `page-header`, #397): the services
   *  in an exception tone, broken first, at most two; else the plain count of
   *  the services that are on. Empty until a status has been read. */
  function headParts() {
    if (statusFailed) return [{ text: 'Status unknown', tone: 'attention' }];
    const ids = Object.keys(SERVICE_NAMES).filter(function (id) { return id in words; });
    if (!ids.length) return [];
    const verbs = { error: 'failing', stale: 'stale', unknown: 'unknown', unavailable: 'unreachable' };
    const parts = [];
    ['danger', 'attention'].forEach(function (tone) {
      ids.forEach(function (id) {
        if (WORD_TONES[words[id]] === tone) parts.push({ text: SERVICE_NAMES[id] + ' ' + verbs[words[id]], tone: tone });
      });
    });
    if (parts.length) return parts.slice(0, 2);
    const on = ids.filter(function (id) { return OFF_WORDS.indexOf(words[id]) < 0; }).length;
    return [{ text: on + ' of ' + ids.length + ' services on', tone: 'muted' }];
  }

  // ------------------------------------------------------ phone access card
  function accessRow(label, ok, text) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.className = ok === null ? '' : (ok ? 'ok' : 'warn');
    dd.textContent = text;
    return [dt, dd];
  }

  // Team mode (Step 12): a row only when it is on — who this browser writes
  // as, and the way back to the pick-your-name step. `team` is GET /api/team's
  // body, or an Error when that call failed (its own "unknown" state).
  function teamRow(team) {
    if (team instanceof Error) return accessRow('Team', false, 'unknown — ' + team.message);
    if (!team || !team.enabled) return [];
    const [dt, dd] = accessRow('Team', null, team.you ? 'you are ' + team.you + ' · ' : 'on — no name picked on this browser · ');
    const change = document.createElement('a');
    change.href = '/login?step=name&next=' + encodeURIComponent('/#settings/access');
    change.textContent = team.you ? 'change name' : 'pick one';
    dd.appendChild(change);
    return [dt, dd];
  }

  function renderAccessCard(st, team) {
    const client = { loopback: 'this PC', token: 'signed in', team: 'team member', public: 'public', denied: 'denied' }[st.auth.client] || st.auth.client;
    els.accessClient.textContent = client;
    els.accessRows.replaceChildren(
      ...accessRow('HTTPS', st.https, st.https ? 'on — Tailscale certificate' : 'off — plain HTTP (run scripts/gen_tailscale_cert.py)'),
      ...accessRow('Access token', st.auth.enabled, st.auth.enabled ? 'configured — other devices sign in at /login' : 'not set — only this PC can use the app (scripts/gen_token.py)'),
      ...accessRow('Password', null, st.auth.password ? 'set — accepted at /login' : 'not set (optional; scripts/set_password.py)'),
      ...teamRow(team),
    );
    els.signOutBtn.hidden = st.auth.client !== 'token' && st.auth.client !== 'team';
  }

  function renderAccessUnknown(message) {
    els.accessRows.replaceChildren(...accessRow('Status', false, 'unknown — ' + message));
  }

  function wireSignOut() {
    els.signOutBtn.addEventListener('click', async function () {
      try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { toast(err.message, 'error'); return; }
      location.assign('/login');
    });
  }

  // ----------------------------------------------- mirror + backup status
  function renderMirrorRow(dd, m) {
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

  // Mirror import diagnostics (issue #84) — recorded as `mirror_events` rows,
  // never as a comment on the task; this row is the "visible at app level"
  // half of the fix, with an inline preview (inspect) and a Clear action.
  async function renderMirrorEventsRow(m) {
    const dd = els.statusMirrorEvents;
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!m || !m.enabled) {
      dd.append(statusPart('off', 'not configured'));
      els.mirrorEventsClear.hidden = true;
      return;
    }
    const n = m.events || 0;
    if (!n) {
      dd.append(statusPart('ok', 'none since the last review'));
      els.mirrorEventsClear.hidden = true;
      return;
    }
    dd.append(statusPart('warn', n + ' since the last review'));
    els.mirrorEventsClear.hidden = false;
    try {
      const r = await api('/api/mirror/events');
      const items = (r.events || []).slice(0, 3).map(function (e) {
        return e.field + ': file said ' + e.file_value + ', kept ' + e.kept_value;
      });
      if (items.length) dd.append(' — ' + items.join('; ') + (n > items.length ? '; +' + (n - items.length) + ' more' : ''));
    } catch (_) { /* the count above still stands */ }
  }

  function wireMirrorEventsClear() {
    els.mirrorEventsClear.addEventListener('click', async function () {
      els.mirrorEventsClear.disabled = true;
      try {
        const r = await api('/api/mirror/events', { method: 'DELETE' });
        toast('Cleared ' + r.cleared + ' import conflict(s)', 'success');
      } catch (err) { toast(err.message || 'Clear failed', 'error'); }
      els.mirrorEventsClear.disabled = false;
      refreshStatus();
    });
  }

  function renderBackupRow(dd, b) {
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

  // --------------------------------------------- folder opener + index card
  function renderOpener(op) {
    const dd = els.statusOpener;
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
    els.openerInstall.textContent = cmd || 'install.txt missing';
    els.openerUninstall.textContent = op.uninstall || '';
    els.openerEnv.textContent = op.env_template || '';
    els.openerCopy.onclick = function () { copyText(cmd, els.openerCopy); };
    els.openerEnvCopy.onclick = function () { copyText(op.env_template || '', els.openerEnvCopy); };
  }

  function renderIndexRow(dd, f) {
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!f || !f.enabled) {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((f && f.reason) || 'unknown'));
      els.reindexBtn.hidden = true;
      return;
    }
    els.reindexBtn.hidden = false;
    const roots = (f.roots || []).map(function (r) { return r.ref + (r.exists ? '' : ' (missing)'); }).join(', ');
    dd.append(
      statusPart(f.indexing ? 'warn' : (f.last_error ? 'warn' : 'ok'), f.indexing ? 'indexing…' : (f.last_error ? 'error' : 'indexed')),
      ' · ', codeEl(roots), ' · ' + (f.entries == null ? '?' : f.entries) + ' folder(s)',
      ' · last indexed ' + (f.last_indexed ? fmtTsShort(f.last_indexed) : '–') + (f.stale && f.last_indexed ? ' (stale, >24 h)' : '')
    );
    if (f.last_error) dd.append(' · ' + f.last_error);
  }

  function wireReindex() {
    els.reindexBtn.addEventListener('click', async function () {
      els.reindexBtn.disabled = true;
      try {
        const r = await api('/api/folders/reindex', { method: 'POST', body: {} });
        toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success');
      } catch (err) { toast(err.message || 'Reindex failed', 'error'); }
      els.reindexBtn.disabled = false;
      refreshStatus();
    });
  }

  // One GET /api/status feeds the Settings pane's Phone access card (https +
  // auth, Step 7), the mirror / backup card (Step 6) and the opener card (Step 9).
  // The card headers carry a state word (on · synced · indexed · off), never a count.
  async function refreshStatus() {
    try {
      const [body, team] = await Promise.all([
        api('/api/status'),
        api('/api/team').catch(function (err) { return err; }),
      ]);
      renderAccessCard(body, team);
      renderMirrorRow(els.statusMirror, body.mirror);
      renderBackupRow(els.statusBackup, body.backup);
      renderMirrorEventsRow(body.mirror).catch(function () {});
      statusFailed = false;
      const on = [body.mirror && body.mirror.enabled, body.backup && body.backup.enabled].filter(Boolean).length;
      // A backup that failed is the row's word, whatever else is on (#397: the
      // header names it, "Backup failing").
      setWord(els.mirrorCardMeta, body.backup && body.backup.last_error ? 'error'
        : on === 2 ? 'both on' : on === 1 ? 'one of two on' : 'off');
      renderOpener(body.opener);
      renderIndexRow(els.statusIndex, body.folders);
      const f = body.folders;
      setWord(els.folderCardMeta, f && f.enabled ? (f.indexing ? 'indexing' : (f.last_error ? 'error' : 'indexed')) : 'index off');
      renderCapture(body.capture);
      renderArchive(body.archive);
      // A run this page did not start (another device): hand it to the Archive
      // pane, which follows it and publishes the outcome back (#262).
      if (body.archive && body.archive.running) opts.onArchiveRun();
      renderCalendar(body.calendar);
      renderVoice(body.voice);
      renderEnrich(body.enrich);
      renderAI(body.ai);
    } catch (err) {
      // An unreachable status is its own visible state, never a stale "Loading…".
      statusFailed = true;
      renderAccessUnknown(err.message);
      els.statusMirror.textContent = 'unknown — ' + err.message;
      els.statusBackup.textContent = 'unknown — ' + err.message;
      els.statusMirrorEvents.textContent = 'unknown — ' + err.message;
      setWord(els.mirrorCardMeta, 'unknown');
      els.statusOpener.textContent = 'unknown — ' + err.message;
      els.statusIndex.textContent = 'unknown — ' + err.message;
      setWord(els.folderCardMeta, 'unknown');
      renderCapture(null);
      renderArchive(null);
      renderCalendar(null);
      renderVoice(null);
      renderEnrich(null);
      renderAI(null);
    }
    opts.onHead();
  }

  // ------------------------------------------------------------- capture
  /** The flagged-email poller's half of `GET /api/status` (#98). Off always
   *  carries its reason — an unconfigured channel is a visible state, not a
   *  quiet nothing. `null` = the status call itself failed. */
  function renderCapture(st) {
    els.captureRunNow.disabled = !(st && st.enabled);
    els.statusCapture.replaceChildren();
    els.statusCaptureRun.replaceChildren();
    els.statusCapture.classList.remove('muted');
    els.statusCaptureRun.classList.remove('muted');
    if (!st) {
      els.statusCapture.textContent = 'unknown';
      els.statusCaptureRun.textContent = '–';
      setWord(els.captureCardMeta, 'unknown');
      return;
    }
    if (!st.enabled) {
      els.statusCapture.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
      els.statusCaptureRun.textContent = '–';
      setWord(els.captureCardMeta, 'off');
      return;
    }
    els.statusCapture.append(
      statusPart(st.last_error ? 'warn' : 'ok', st.last_error ? 'error' : 'enabled'),
      ' · every ' + st.poll_minutes + ' min',
      st.next_run ? ' · next ' + fmtTsShort(st.next_run) : ''
    );
    if (st.last_error) els.statusCapture.append(' · ' + st.last_error);
    const r = st.last_result;
    if (!st.last_run) {
      els.statusCaptureRun.textContent = 'not yet';
    } else {
      els.statusCaptureRun.append(fmtTsShort(st.last_run));
      if (r) {
        els.statusCaptureRun.append(
          ' · ' + r.listed + ' flagged · ' + r.created + ' new'
          + (r.dismissed ? ' · ' + r.dismissed + ' dismissed' : '')
          + (r.errors && r.errors.length ? ' · ' + r.errors.length + ' error(s)' : '')
        );
      }
    }
    setWord(els.captureCardMeta, st.last_error ? 'error' : (st.last_run ? 'checked' : 'on'));
  }

  function wireCaptureRunNow() {
    els.captureRunNow.addEventListener('click', async function () {
      els.captureRunNow.disabled = true;
      try {
        const r = await api('/api/capture/email/run', { method: 'POST', body: {} });
        toast('Capture: ' + r.listed + ' flagged · ' + r.created + ' new task(s)', 'success');
        if (r.created) opts.onCaptured();
      } catch (err) { toast(err.message || 'Capture failed', 'error'); }
      els.captureRunNow.disabled = false;
      refreshStatus();
    });
  }

  // ------------------------------------------------------------- archive
  /** The batch archiver's half of `GET /api/status` (#157–#159, #167): where
   *  the archiver lives and its threshold — the two rows of the Email
   *  archiving sheet that archive.js does not draw (its head names the state,
   *  the model and the runs) — and the row's word. Not configured carries its
   *  reason in archive.js's Archiver row; `null` = the status call itself
   *  failed, which is "unknown" and not the same as "off". This module never
   *  follows a live run itself (#262): archive.js does, and publishes each
   *  status it reads back here through `renderArchive` — so "running"
   *  resolves into the run's own counts when its poll finishes. */
  function renderArchive(st) {
    const rows = [els.statusArchiveRepo, els.statusArchiveThreshold];
    rows.forEach(function (el) { el.replaceChildren(); el.classList.remove('muted'); });
    if (!st) {
      rows.forEach(function (el) { el.textContent = 'unknown'; });
      setWord(els.archiveCardMeta, 'unknown');
    } else if (!st.configured) {
      rows.forEach(function (el) { el.textContent = '–'; });
      setWord(els.archiveCardMeta, 'off');
    } else {
      els.statusArchiveRepo.append(codeEl(st.repo || 'unknown'));
      els.statusArchiveThreshold.append(
        pct(st.confidence_threshold),
        ' · ' + (st.candidates == null ? '?' : st.candidates) + ' folder(s) ranked per mail'
      );
      setWord(els.archiveCardMeta, archiveWord(st));
    }
    opts.onHead();
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

  // ------------------------------------------------------------ calendar
  //: The state word in the row and the card header, per `calendar.state`.
  const CALENDAR_WORDS = {
    ok: 'reading', bad_url: 'address refused', unreachable: 'unreachable',
    timeout: 'timed out', parse_error: 'not a calendar',
  };

  /** The Today lane's half of `GET /api/status` (#96). Off always carries its
   *  reason; every failure keeps its own word; `null` = the status call itself
   *  failed, which is "unknown", not "off". The source is the host only — the
   *  address is a secret and the API never sends it. */
  function renderCalendar(st) {
    const rows = [els.statusCalendar, els.statusCalendarSource, els.statusCalendarFetched];
    rows.forEach(function (dd) { dd.replaceChildren(); dd.classList.remove('muted'); });
    els.calendarRefresh.disabled = !(st && st.configured && st.state !== 'off');
    if (!st) {
      rows.forEach(function (dd) { dd.textContent = 'unknown'; });
      setWord(els.calendarCardMeta, 'unknown');
      return;
    }
    if (!st.configured || st.state === 'off') {
      els.statusCalendar.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
      els.statusCalendarSource.textContent = '–';
      els.statusCalendarFetched.textContent = '–';
      setWord(els.calendarCardMeta, 'off');
      return;
    }
    const ok = st.state === 'ok';
    const word = CALENDAR_WORDS[st.state] || st.state;
    els.statusCalendar.append(statusPart(ok ? 'ok' : 'warn', word));
    if (!ok && st.failing_since) els.statusCalendar.append(' since ' + fmtTsShort(st.failing_since));
    if (ok && st.events_today != null) {
      els.statusCalendar.append(' · ' + st.events_today + ' event(s) today');
    }
    if (st.skipped_recurring) els.statusCalendar.append(' · ' + st.skipped_recurring + ' recurring not checked');
    if (st.unreadable) els.statusCalendar.append(' · ' + st.unreadable + ' unreadable');
    if (st.error) els.statusCalendar.append(' — ' + st.error);
    els.statusCalendarSource.append(st.source ? codeEl(st.source) : 'unknown');
    els.statusCalendarSource.append(' · every ' + st.refresh_minutes + ' min · ' + st.timeout_seconds + ' s timeout');
    els.statusCalendarFetched.textContent = st.fetched_at
      ? fmtTsShort(st.fetched_at) + (st.stale ? ' (stale)' : '') : 'never';
    setWord(els.calendarCardMeta, ok ? 'on' : (st.stale ? 'stale' : 'error'));
  }

  function wireCalendarRefresh() {
    els.calendarRefresh.addEventListener('click', async function () {
      els.calendarRefresh.disabled = true;
      try {
        const group = await api('/api/calendar/refresh', { method: 'POST', body: {} });
        opts.onCalendar(group);
        if (group.state === 'ok') {
          toast('Calendar: ' + (group.events.length + group.all_day.length) + ' event(s) today', 'success');
        } else {
          toast('Calendar: ' + (CALENDAR_WORDS[group.state] || group.state) + ' — ' + (group.error || group.reason || 'unknown'), 'error');
        }
      } catch (err) { toast(err.message || 'Refresh failed', 'error'); }
      refreshStatus();
    });
  }

  // --------------------------------------------------------------- voice
  /** The whisper endpoint's half of `GET /api/status` (#92). Unreachable
   *  always carries its reason — the same sentence the quick-add mic's hint
   *  shows. `null` = the status call itself failed, which is "not
   *  established", not "off". */
  function renderVoice(st) {
    els.statusVoice.replaceChildren();
    els.statusVoiceUrl.replaceChildren();
    els.statusVoice.classList.remove('muted');
    els.statusVoiceUrl.classList.remove('muted');
    if (!st) {
      els.statusVoice.textContent = 'unknown';
      els.statusVoiceUrl.textContent = '–';
      setWord(els.voiceCardMeta, 'unknown');
      return;
    }
    els.statusVoiceUrl.append(st.url ? codeEl(st.url) : 'not set');
    if (!st.enabled) {
      els.statusVoice.append(statusPart('off', 'not reachable'), ' — ' + (st.reason || 'unknown'));
      setWord(els.voiceCardMeta, 'off');
      return;
    }
    // Which endpoint answered matters: the hub means the fleet's transcribe
    // role (parakeet first), the fallback means the local CPU whisper server.
    const serving = { hub: 'hub', fallback: 'local whisper (fallback)' }[st.serving] || 'unknown';
    // The live-transcript cadence (#146). Absent is not "off": the install
    // did not say, and saying "off" for it would be a claim nobody made.
    const every = st.partial_interval_seconds;
    const live = typeof every !== 'number' ? 'live transcript unknown'
      : every > 0 ? 'live every ' + (+every.toFixed(2)) + 's'
        : 'live transcript off';
    els.statusVoice.append(
      statusPart('ok', 'reachable'),
      ' · ' + serving,
      ' · ' + live,
      st.checked_at ? ' · checked ' + fmtTsShort(st.checked_at) : ''
    );
    setWord(els.voiceCardMeta, st.serving === 'fallback' ? 'fallback' : 'on');
  }

  /** The light model that turns a spoken sentence into a title and a
   *  description (#147). Off is a state with a reason, not a blank: a
   *  spoken line still becomes a task, it just keeps the deterministic
   *  parse — and this row is where you find that out. */
  function renderEnrich(st) {
    els.statusEnrich.replaceChildren();
    els.statusEnrich.classList.remove('muted');
    if (!st) { els.statusEnrich.textContent = 'unknown'; return; }
    if (!st.enabled) {
      els.statusEnrich.append(statusPart('off', 'not reachable'),
        ' — ' + (st.reason || 'unknown') + ' · the spoken line keeps the plain parse');
      return;
    }
    els.statusEnrich.append(statusPart('ok', 'reachable'), ' · ', codeEl(st.model || 'unknown'));
  }

  // --------------------------------------------------------- AI triage
  function renderAI(st) {
    els.statusAI.replaceChildren();
    els.statusAIModel.replaceChildren();
    els.statusAI.classList.remove('muted');
    els.statusAIModel.classList.remove('muted');
    if (!st) {
      els.statusAI.textContent = 'unknown';
      els.statusAIModel.textContent = '–';
      setWord(els.aiCardMeta, 'unknown');
      return;
    }
    els.statusAIModel.append(st.model ? codeEl(st.model) : 'not set');
    if (!st.enabled) {
      const label = st.configured ? 'not reachable' : 'off';
      els.statusAI.append(statusPart('off', label), ' — ' + (st.reason || 'unknown'));
      setWord(els.aiCardMeta, st.configured ? 'unavailable' : 'off');
      return;
    }
    els.statusAI.append(
      statusPart('ok', 'reachable'),
      st.checked_at ? ' · checked ' + fmtTsShort(st.checked_at) : ''
    );
    setWord(els.aiCardMeta, 'on');
  }

  // ------------------------------------------------------------ issue sync
  /** The Settings row's half of the issue-provider status; the sync call
   *  itself stays with the bootstrap (the drawer and the palette make it too). */
  function renderIssues(st) {
    drawIssues(st);
    opts.onHead();
  }

  function drawIssues(st) {
    const configured = !!(st && st.enabled);
    els.issuesSyncNow.disabled = !configured;
    els.statusIssues.replaceChildren();
    els.statusIssuesSync.replaceChildren();
    els.statusIssues.classList.remove('muted');
    els.statusIssuesSync.classList.remove('muted');
    if (!st) {
      els.statusIssues.textContent = 'unknown';
      els.statusIssuesSync.textContent = '–';
      setWord(els.issuesCardMeta, 'unknown');
      return;
    }
    if (!configured) {
      els.statusIssues.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
      els.statusIssuesSync.textContent = '–';
      setWord(els.issuesCardMeta, 'off');
      return;
    }
    els.statusIssues.append(
      statusPart(st.last_error ? 'warn' : 'ok', st.last_error ? 'error' : 'enabled'),
      ' · ', codeEl(st.provider), ' · every ' + st.sync_minutes + ' min',
      st.next_run ? ' · next ' + fmtTsShort(st.next_run) : ''
    );
    if (st.last_error) els.statusIssues.append(' · ' + (st.last_error_code ? st.last_error_code + ': ' : '') + st.last_error);
    const r = st.last_result;
    if (!st.last_sync) {
      els.statusIssuesSync.textContent = 'not yet';
    } else {
      els.statusIssuesSync.append(fmtTsShort(st.last_sync));
      if (r) {
        els.statusIssuesSync.append(' · ' + r.listed + ' open issue(s) · ' + r.created + ' new · ' + r.retitled + ' retitled · ' + r.reopened + ' reopened · ' + r.closed + ' closed' + (r.errors && r.errors.length ? ' · ' + r.errors.length + ' error(s)' : ''));
      }
    }
    if (st.repos && st.repos.length) els.statusIssuesSync.append(' · repos: ' + st.repos.join(', '));
    setWord(els.issuesCardMeta, st.last_error ? 'error' : (st.last_sync ? 'synced' : 'on'));
  }

  /** The palette's phone entry (#316) — the card only hosts the button. */
  function wirePaletteOpen() {
    els.paletteOpen.addEventListener('click', function () { opts.onOpenPalette(); });
  }

  /** Text size (#314): inline in its row since #397 — the control is its own
   *  value; the vendored binding does the storing and stamping. */
  function wireTextSize() {
    bindTextSize(els.textSizeControl, 'task-os');
  }

  // ------------------------------------------------------ row actions
  /** Row actions (#311): the two swipes and the ⋯ menu's list, choices from
   *  the one action table. Every change is stored at once (rowprefs.js) and
   *  handed to `opts.onRowActions`, which redraws the rows — a menu reads its
   *  list when its row is drawn. An action a swipe runs is ticked and locked
   *  in the list, so the menu always keeps the tap path to it (WCAG 2.5.1). */
  function renderRowActions(focusId, focusDir) {
    const p = rowPrefs();
    els.rowActionsMeta.textContent = isDefault(p) ? 'Default' : 'Custom';
    [[els.swipeRight, p.right], [els.swipeLeft, p.left]].forEach(function (pair) {
      const sel = pair[0];
      sel.replaceChildren();
      [['', 'Nothing']].concat(ACTIONS.map(function (a) { return [a.id, a.label]; })).forEach(function (o) {
        const opt = document.createElement('option');
        opt.value = o[0];
        opt.textContent = o[1];
        opt.selected = o[0] === pair[1];
        sel.appendChild(opt);
      });
    });
    // the chosen list in its order, then every other action, unticked
    const rest = ACTIONS.map(function (a) { return a.id; }).filter(function (id) { return p.menu.indexOf(id) < 0; });
    const ids = p.menu.concat(rest);
    els.rowMenuList.replaceChildren();
    ids.forEach(function (id, i) {
      const a = actionById(id);
      const shown = p.menu.indexOf(id) >= 0;
      const swipe = id === p.right ? 'swipe right' : (id === p.left ? 'swipe left' : null);
      const li = document.createElement('li');
      li.className = 'row-actions-item';
      li.dataset.action = id;
      // A pressed-state square, not a bare checkbox: the .icon-button box is a real
      // 44px target (34 painted + its expansion), which a 16px checkbox is not.
      const listed = shown || !!swipe;
      const tick = document.createElement('button');
      tick.type = 'button';
      tick.className = 'icon-button row-actions-tick';
      tick.setAttribute('aria-pressed', listed ? 'true' : 'false');
      tick.setAttribute('aria-label', 'Show ' + a.label + ' in the menu');
      tick.innerHTML = icon(listed ? 'square-check' : 'square');
      tick.disabled = !!swipe;
      tick.addEventListener('click', function () { toggleMenu(id, !listed, 'tick'); });
      const name = document.createElement('span');
      name.className = 'row-actions-name';
      name.textContent = a.label;
      li.append(tick, name);
      if (swipe) {
        const hint = document.createElement('span');
        hint.className = 'row-actions-hint muted';
        hint.textContent = 'used by ' + swipe;
        li.appendChild(hint);
      }
      [['up', -1, 'chevron-up'], ['down', 1, 'chevron-down']].forEach(function (m) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'icon-button row-actions-move';
        b.dataset.move = m[0];
        b.setAttribute('aria-label', 'Move ' + a.label + ' ' + m[0]);
        b.innerHTML = icon(m[2]);
        // only a listed action has a place to move; the first can't go up, the last can't go down
        b.disabled = !shown || (m[1] < 0 ? i === 0 : i === p.menu.length - 1);
        b.addEventListener('click', function () { move(id, m[1], m[0]); });
        li.appendChild(b);
      });
      els.rowMenuList.appendChild(li);
    });
    if (focusId) {
      // the control just used, on its rebuilt row (a move keeps its direction
      // while it still can go that way)
      const row = '[data-action="' + focusId + '"] ';
      const back = focusDir === 'tick' ? els.rowMenuList.querySelector(row + '.row-actions-tick')
        : (els.rowMenuList.querySelector(row + '[data-move="' + focusDir + '"]:not(:disabled)')
          || els.rowMenuList.querySelector(row + '[data-move]:not(:disabled)'));
      if (back) back.focus();
    }
  }

  function saveRowActions(next, focusId, focusDir) {
    setRowPrefs(next);
    renderRowActions(focusId, focusDir);
    if (opts.onRowActions) opts.onRowActions();
  }

  function toggleMenu(id, on) {
    const p = rowPrefs();
    const menu = p.menu.filter(function (x) { return x !== id; });
    if (on) menu.push(id);
    saveRowActions(Object.assign({}, p, { menu: menu }), id, 'tick');
  }

  function move(id, by, dir) {
    const p = rowPrefs();
    const menu = p.menu.slice();
    const i = menu.indexOf(id);
    const j = i + by;
    if (i < 0 || j < 0 || j >= menu.length) return;
    menu.splice(i, 1);
    menu.splice(j, 0, id);
    saveRowActions(Object.assign({}, p, { menu: menu }), id, dir);
  }

  function wireRowActions() {
    els.swipeRight.addEventListener('change', function () {
      saveRowActions(Object.assign({}, rowPrefs(), { right: els.swipeRight.value }));
    });
    els.swipeLeft.addEventListener('change', function () {
      saveRowActions(Object.assign({}, rowPrefs(), { left: els.swipeLeft.value }));
    });
    els.rowActionsReset.addEventListener('click', function () {
      setRowPrefs(null);
      renderRowActions();
      if (opts.onRowActions) opts.onRowActions();
    });
    renderRowActions();
  }

  function wireIssueSyncNow() {
    els.issuesSyncNow.addEventListener('click', function () {
      // the button is the app's one sync control now (#301): it spins while the pass runs
      els.issuesSyncNow.classList.add('is-busy');
      opts.onSyncIssues().catch(function () {}).finally(function () { els.issuesSyncNow.classList.remove('is-busy'); });
    });
  }

  // ---------------------------------------------------------- search card
  /** Which indexes this install can query (GET /api/search/status). */
  async function refreshSearchStatus() {
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
    setWord(els.searchCardMeta, adapters ? (on ? 'indexed' : 'off') : 'unknown');
    opts.onHead();
    opts.onSearchStatus();
  }

  // ------------------------------------------------------------ sheets
  // One sheet body per row (`data-sheet`), all inside the one #settingsSheet.
  const bodies = {};
  els.sheet.querySelectorAll('.settings-sheet[data-sheet]').forEach(function (s) { bodies[s.dataset.sheet] = s; });
  let openKey = null;

  function rowFor(key) {
    return els.pane.querySelector('[data-settings-sheet="' + key + '"]');
  }

  /** Show `key`'s sheet (the bootstrap calls it for `#settings/<key>`): its
   *  body alone, titled by its row's label, the row marked as the selected
   *  one (beside the detail pane on a wide screen). False for an unknown key. */
  function showSheet(key) {
    if (!bodies[key]) return false;
    const fresh = openKey !== key;
    Object.keys(bodies).forEach(function (k) { bodies[k].hidden = k !== key; });
    const row = rowFor(key);
    els.sheetTitle.textContent = row ? row.querySelector('.action-row-title').textContent : '';
    els.pane.querySelectorAll('[data-settings-sheet]').forEach(function (r) {
      if (r === row) r.setAttribute('aria-current', 'true');
      else r.removeAttribute('aria-current');
    });
    els.sheet.hidden = false;
    document.body.dataset.settingsSheet = key;
    openKey = key;
    if (fresh) {
      els.sheet.querySelector('.settings-sheet-scroll').scrollTop = 0;
      els.sheet.querySelector('.settings-sheet-close').focus({ preventScroll: true });
    }
    return true;
  }

  /** Close the sheet; focus goes back to its row while that is on screen. */
  function hideSheet() {
    if (openKey == null) return;
    const row = rowFor(openKey);
    openKey = null;
    els.sheet.hidden = true;
    delete document.body.dataset.settingsSheet;
    if (row) row.removeAttribute('aria-current');
    if (row && !els.pane.hidden && els.sheet.contains(document.activeElement)) row.focus({ preventScroll: true });
  }

  function wireSheets() {
    els.pane.querySelectorAll('[data-settings-sheet]').forEach(function (row) {
      row.addEventListener('click', function () { opts.onOpenSheet(row.dataset.settingsSheet); });
    });
    // Instant model: every control applies as it changes, so Done only closes.
    els.sheet.querySelector('.settings-sheet-close').addEventListener('click', function () { opts.onCloseSheet(); });
    els.sheet.querySelector('.settings-sheet-done').addEventListener('click', function () { opts.onCloseSheet(); });
  }

  wireSignOut();
  wireReindex();
  wireMirrorEventsClear();
  wireIssueSyncNow();
  wirePaletteOpen();
  wireTextSize();
  wireRowActions();
  wireCaptureRunNow();
  wireCalendarRefresh();
  wireSheets();

  return {
    refreshStatus: refreshStatus,
    renderArchive: renderArchive,
    refreshSearchStatus: refreshSearchStatus,
    renderIssues: renderIssues,
    showSheet: showSheet,
    hideSheet: hideSheet,
    currentSheet: function () { return openKey; },
    headParts: headParts,
  };
}
