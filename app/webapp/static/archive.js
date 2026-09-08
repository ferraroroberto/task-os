/* task-os — the Archive tab: run the batch, read the report, fix what is wrong (#159).
 *
 * Step 3/3 of batch email archiving. One button files the whole Outlook Inbox
 * through email-archiver (#157) with the local model picking the folder (#158);
 * this module is the screen that starts that run and then lets a human review
 * every mail it touched. It is **read-mostly over the Step 1 API** — no domain
 * rule lives here:
 *
 *   POST /api/archive/run {limit?}       start one run (202, then it polls)
 *   GET  /api/archive/runs?limit=        the run picker
 *   GET  /api/archive/runs/{id}          the run + its rows — the whole report
 *   POST /api/archive/items/{id}/accept  {hint?}          "I have seen this"
 *   POST /api/archive/items/{id}/move    {folder, hint?}  file it where I say
 *   POST /api/archive/items/{id}/revert                   undo this one mail
 *
 * The four review levels the report offers per row are exactly the API's, and
 * which of them a row gets is decided by that row's own state, never by taste:
 * *accept* only reaches a row that asks for a human (`needs_review`, `failed` —
 * an `archived` row is finished, not reviewed, and the API answers 409 there),
 * *revert* only reaches a row with files on disk, and *move* reaches both those
 * and a `needs_review` mail still sitting in the Inbox — filing it for the
 * first time is the commonest thing anyone does on this screen. A control that
 * would 409 is not rendered; a row that genuinely offers nothing says so.
 *
 * The discarded candidates come straight off the row (`candidates`, kept
 * verbatim by the run), so offering them costs no re-plan. The optional
 * one-line **hint** rides the accept/move body into `archive_corrections` and
 * becomes a few-shot line in every later prompt (#158) — explained once, not
 * repeated.
 *
 * Two renderings of one report, like every other view here: the full-width
 * grid on a wide screen, stacked cards with the actions behind a per-row
 * disclosure under 768 px. Both are built from the same row objects.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { api } from './api.js';
import { confirmDialog } from './confirm.js';
import { mountFolderPicker, resolveFolderRef } from './folderpick.js';
import { fmtTsShort, folderChip } from './format.js';
import { toast } from './toast.js';

const RUNS_LIMIT = 20;
//: How often the screen re-reads a run that is still going. The run itself is
//: minutes-scale over COM; this is only how often the counters move.
const POLL_MS = 1500;
const PHONE_MQ = '(max-width: 767px)';
//: The two states a human can still say "seen" about (the API's own
//: REVIEWABLE_STATUSES — accept answers 409 on anything else).
const REVIEWABLE = ['needs_review', 'failed'];
//: The two states in which files actually exist on disk, so an undo has
//: something to undo. `failed` joins them only when files were written.
const FILED = ['archived', 'moved'];
const STATE_WORDS = {
  archived: 'filed',
  moved: 'moved by you',
  needs_review: 'needs you',
  failed: 'failed',
  reverted: 'reverted',
};
const STATE_TONE = {
  archived: 'ok', moved: 'ok', needs_review: 'warn', failed: 'warn', reverted: 'off',
};
const MAX_HINT = 500;

/**
 * Wire the Archive pane once and hand back the bootstrap's handle.
 * @param {{onStatus: (archive: object|null) => void, onChanged: () => void}} opts
 *        `onStatus` publishes `GET /api/status`'s `archive` block so the Board's
 *        Inbox header can show what still needs a human; `onChanged` fires when
 *        a run or a review action has changed something outside this pane.
 * @returns {{refresh: () => Promise<void>, refreshStatus: () => Promise<void>}}
 */
export function mountArchive(opts) {
  const els = {
    run: document.getElementById('archiveRun'),
    runLabel: document.getElementById('archiveRunLabel'),
    limit: document.getElementById('archiveLimit'),
    progress: document.getElementById('archiveProgress'),
    status: document.getElementById('statusArchive'),
    lastRun: document.getElementById('statusArchiveRun'),
    recent: document.getElementById('statusArchiveRecent'),
    pick: document.getElementById('archiveRunPick'),
    acceptAll: document.getElementById('archiveAcceptAll'),
    host: document.getElementById('archiveHost'),
  };

  let status = null;    // GET /api/status → archive; null = the call itself failed
  let runs = [];        // the picker's list, latest first
  let run = null;       // the selected run WITH its items
  let runId = null;
  let poll = 0;         // setTimeout handle between two polls of a live run
  // Whether this pane is following a run *at all* — true across the gap where
  // `poll` is 0 because a tick is in flight. Re-entering the tab mid-run must
  // not start a second chain that double-polls and double-toasts.
  let polling = false;
  let busy = false;     // a run or a review action is in flight

  // ------------------------------------------------------------- the head
  function statusPart(tone, text) {
    const s = document.createElement('span');
    s.className = 'status-' + tone;
    s.textContent = text;
    return s;
  }

  function codeEl(text) {
    const c = document.createElement('code');
    c.textContent = text;
    return c;
  }

  /** The service's own state. Off always carries its reason; a failed status
   *  call is "unknown", which is not the same as "off". */
  function renderHead() {
    els.status.replaceChildren();
    els.status.classList.remove('muted');
    if (!status) {
      // The status call itself failed: unknown, which is not "off" — and the
      // rows below it must say so too rather than keep a stale reading.
      els.status.append(statusPart('warn', 'unknown'));
      els.lastRun.textContent = 'unknown';
      els.recent.textContent = 'unknown';
      els.run.disabled = true;
      els.limit.disabled = true;
      return;
    }
    if (!status.configured) {
      els.status.append(statusPart('off', 'not configured'), ' — ' + (status.reason || 'unknown'));
      els.run.disabled = true;
      els.limit.disabled = true;
    } else {
      els.status.append(
        statusPart(status.last_error ? 'warn' : 'ok', status.running ? 'running' : 'ready'),
        ' · model ', codeEl(status.model || 'none'),
        ' · batches of ' + status.batch_size + ' · ' + status.examples + ' corrections remembered'
      );
      if (status.last_error) els.status.append(' · last error: ' + status.last_error);
      els.run.disabled = busy || !!status.running;
      els.limit.disabled = els.run.disabled;
    }
    els.runLabel.textContent = status && status.running ? 'Archiving…' : 'Archive Inbox now';
    renderLastRun(status.last_run);
  }

  function renderLastRun(last) {
    els.lastRun.replaceChildren();
    els.lastRun.classList.remove('muted');
    if (!last) { els.lastRun.textContent = 'never'; return; }
    els.lastRun.append(
      fmtTsShort(last.finished_at || last.started_at), ' · ',
      statusPart(last.status === 'failed' ? 'warn' : last.status === 'running' ? 'warn' : 'ok', last.status),
      ' · ' + counts(last)
    );
    if (last.agreement != null) {
      els.lastRun.append(' · model agreed with the suggester on ' + pct(last.agreement));
    }
    if (last.error) els.lastRun.append(' · ' + last.error);
  }

  function counts(r) {
    return (r.planned || 0) + ' mail(s) · ' + (r.archived || 0) + ' filed · '
      + (r.needs_review || 0) + ' need you · ' + (r.failed || 0) + ' failed';
  }

  /** What the runs on the picker add up to. Derived from the run rows on
   *  screen and named as such — never presented as an all-time accept rate,
   *  which nothing here measures. */
  function renderRecent() {
    els.recent.replaceChildren();
    els.recent.classList.remove('muted');
    const done = runs.filter(function (r) { return r.status !== 'running'; });
    if (!done.length) { els.recent.textContent = 'no finished run yet'; return; }
    const total = done.reduce(function (a, r) { return a + (r.planned || 0); }, 0);
    const filed = done.reduce(function (a, r) { return a + (r.archived || 0); }, 0);
    const review = done.reduce(function (a, r) { return a + (r.needs_review || 0); }, 0);
    els.recent.append(
      done.length + ' run(s) · ' + total + ' mail(s) · ' + filed + ' filed · ' + review + ' needed you'
    );
    if (total) els.recent.append(' (' + pct(filed / total) + ' filed straight away)');
  }

  function pct(value) {
    return Math.round(Number(value) * 100) + '%';
  }

  // --------------------------------------------------------- the run picker
  function renderPicker() {
    els.pick.replaceChildren();
    if (!runs.length) {
      const o = document.createElement('option');
      o.textContent = 'no runs yet';
      els.pick.appendChild(o);
      els.pick.disabled = true;
      return;
    }
    els.pick.disabled = false;
    runs.forEach(function (r) {
      const o = document.createElement('option');
      o.value = String(r.id);
      o.textContent = '#' + r.id + ' · ' + fmtTsShort(r.started_at) + ' · ' + r.status
        + ' · ' + (r.planned || 0) + ' mail(s)';
      els.pick.appendChild(o);
    });
    if (runId == null || !runs.some(function (r) { return r.id === runId; })) runId = runs[0].id;
    els.pick.value = String(runId);
  }

  // ------------------------------------------------------------ the report
  /** The last three components of a folder path — enough to recognise it; the
   *  full path is the title. The archiver reports Windows separators. */
  function shortFolder(path) {
    const parts = String(path || '').split(/[\\/]+/).filter(Boolean);
    return parts.slice(-3).join(' › ') || String(path || '');
  }

  function stateChip(item) {
    const s = document.createElement('span');
    s.className = 'archive-state status-' + (STATE_TONE[item.status] || 'off');
    s.textContent = STATE_WORDS[item.status] || item.status;
    if (item.decided_at) s.title = 'reviewed ' + fmtTsShort(item.decided_at);
    return s;
  }

  function destinationEl(item) {
    const el = document.createElement('span');
    el.className = 'archive-dest';
    if (!item.chosen_folder) {
      el.classList.add('muted');
      el.textContent = 'still in the Inbox';
      return el;
    }
    el.textContent = shortFolder(item.chosen_folder);
    el.title = item.chosen_folder;
    return el;
  }

  /** The archived files as opener chips — the same per-PC `taskos://` link
   *  every folder chip in the app carries, so a `.msg` opens in the mail
   *  client on whichever PC is looking. */
  function filesEl(item) {
    const el = document.createElement('span');
    el.className = 'archive-files folder-chips';
    if (!item.files.length) {
      el.classList.add('muted');
      el.textContent = item.attachments ? '– (' + item.attachments + ' attachment(s))' : '–';
      return el;
    }
    item.files.forEach(function (path) {
      const name = String(path).split(/[\\/]+/).pop();
      el.appendChild(folderChip(path, { label: name, icon: /\.msg$/i.test(name) ? 'mail' : 'file-text' }));
    });
    return el;
  }

  function confidenceEl(item) {
    const el = document.createElement('span');
    if (item.confidence == null) {
      el.className = 'muted';
      el.textContent = '–';
      return el;
    }
    el.className = 'archive-confidence';
    el.textContent = pct(item.confidence);
    // rank 0 = the model landed on the archiver's own top candidate
    el.title = item.chosen_rank === 0
      ? 'the model picked the archiver’s own top candidate'
      : item.chosen_rank == null ? 'no ranked pick' : 'the model picked candidate #' + (item.chosen_rank + 1);
    return el;
  }

  function reasonEl(item) {
    const el = document.createElement('span');
    el.className = 'archive-reason';
    const text = item.error ? (item.reason ? item.reason + ' · ' + item.error : item.error)
      : (item.reason || '');
    el.textContent = text || '–';
    el.title = text;
    if (item.error) el.classList.add('archive-reason-error');
    return el;
  }

  function isFiled(item) {
    return FILED.indexOf(item.status) >= 0 || (item.status === 'failed' && item.files.length > 0);
  }

  function canMove(item) {
    return isFiled(item) || item.status === 'needs_review';
  }

  // ------------------------------------------------------------- actions
  function actionButton(glyph, label, handler) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-ghost archive-action';
    b.innerHTML = icon(glyph);
    const t = document.createElement('span');
    t.textContent = label;
    b.appendChild(t);
    b.addEventListener('click', function () {
      runAction(b, handler);
    });
    return b;
  }

  /** One place where an action disables its button, runs, and re-reads the
   *  world — so no two actions can race the archiver's single lock. */
  function runAction(button, handler) {
    if (busy) return;
    busy = true;
    button.disabled = true;
    Promise.resolve()
      .then(handler)
      .catch(function (err) { if (err) toast(err.message || 'Action failed', 'error'); })
      .then(function () {
        busy = false;
        return reload();
      });
  }

  function acceptItem(item, hint) {
    return api('/api/archive/items/' + item.id + '/accept', {
      method: 'POST', body: hint ? { hint: hint } : {},
    }).then(function () { toast('Marked as reviewed', 'success'); });
  }

  /**
   * File `item` into `folder`.
   * @param {boolean} known  the folder came off the row's own candidates, so it
   *        is already a path this install produced — it goes to the API as it
   *        is (which folds it onto the placeholders itself). Only a folder a
   *        human *typed* is folded here first, where the "Stored as …" answer
   *        is the feedback that the path was understood.
   */
  async function moveItem(item, folder, hint, known) {
    const ref = known ? folder : await resolveFolderRef(folder);
    if (ref === undefined || ref === null) return;   // already toasted / nothing typed
    const ok = await confirmDialog({
      title: isFiled(item) ? 'Move this mail?' : 'File this mail?',
      lines: [
        item.subject || '(no subject)',
        isFiled(item)
          ? 'Its archived file is deleted and the mail is filed again under ' + ref + '.'
          : 'The mail leaves the Inbox and is filed under ' + ref + '.',
        hint ? 'Remembered as: “' + hint + '”' : null,
      ],
      action: isFiled(item) ? 'Move it' : 'File it',
    });
    if (!ok) return;
    const body = { folder: ref };
    if (hint) body.hint = hint;
    await api('/api/archive/items/' + item.id + '/move', { method: 'POST', body: body });
    toast('Filed under ' + shortFolder(ref), 'success');
  }

  async function revertItem(item) {
    const ok = await confirmDialog({
      title: 'Undo this mail?',
      lines: [
        item.subject || '(no subject)',
        'Its archived file(s) are deleted and the mail goes back to the Outlook Inbox.',
      ],
      warn: 'The file is deleted, not moved to the recycle bin.',
      action: 'Undo it',
    });
    if (!ok) return;
    await api('/api/archive/items/' + item.id + '/revert', { method: 'POST', body: {} });
    toast('Back in the Inbox', 'success');
  }

  /** The *Move to…* panel: the discarded candidates the run already ranked,
   *  *Other folder…* over the shared folder-index picker, and the one optional
   *  hint that explains the correction to the next run.
   *
   *  Returned in two pieces — the toggle and the body — because the caller
   *  decides where the body goes. In the grid it is a full-width row of its
   *  own **under** the mail's row: a panel inside the last cell widened that
   *  column and squeezed *Why* down to one word a line. On the phone card it
   *  sits straight under the actions.
   *  @param {{onToggle?: (open: boolean) => void}} [hooks]
   */
  function movePanel(item, hooks) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'button-ghost archive-action archive-move-toggle';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.innerHTML = icon('folder');
    const label = document.createElement('span');
    label.textContent = isFiled(item) ? 'Move to…' : 'File it…';
    toggle.appendChild(label);

    const body = document.createElement('div');
    body.className = 'archive-move-body';
    body.hidden = true;
    toggle.addEventListener('click', function () {
      const open = body.hidden;
      body.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.classList.toggle('is-on', open);
      if (hooks && hooks.onToggle) hooks.onToggle(open);
    });

    const hint = document.createElement('input');
    hint.type = 'text';
    hint.className = 'input-native archive-hint';
    hint.maxLength = MAX_HINT;
    hint.placeholder = 'Why (optional) — remembered for the next run';
    hint.setAttribute('aria-label', 'Why this folder (optional)');

    // The candidates this run already ranked and did not use. The one it did
    // use is left out for a filed mail (the API refuses re-filing a mail into
    // the folder it is already in) and kept for a `needs_review` one, where it
    // is the pick the model was not confident enough about — the likeliest
    // answer on the screen.
    const candidates = (item.candidates || []).filter(function (c) {
      return c && c.folder_path && !(isFiled(item) && sameFolder(c.folder_path, item.chosen_folder));
    });
    if (candidates.length) {
      const list = document.createElement('ul');
      list.className = 'archive-cands';
      candidates.forEach(function (c) {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'button-ghost archive-cand';
        b.title = (isFiled(item) ? 'Move into ' : 'Archive here: ') + c.folder_path;
        const name = document.createElement('span');
        name.className = 'archive-cand-name';
        name.textContent = c.display_name || shortFolder(c.folder_path);
        const path = document.createElement('span');
        path.className = 'archive-cand-path';
        path.textContent = shortFolder(c.folder_path);
        const score = document.createElement('span');
        score.className = 'archive-cand-score';
        score.textContent = c.score == null ? '' : Number(c.score).toFixed(2);
        b.append(name, path, score);
        b.addEventListener('click', function () {
          runAction(b, function () { return moveItem(item, c.folder_path, hint.value.trim(), true); });
        });
        li.appendChild(b);
        list.appendChild(li);
      });
      body.appendChild(list);
    } else {
      const none = document.createElement('p');
      none.className = 'muted archive-move-none';
      none.textContent = 'No other folder was ranked for this mail — name one below.';
      body.appendChild(none);
    }

    // Other folder…: the same field + index picker the drawer and quick-add use.
    const other = document.createElement('div');
    other.className = 'archive-other';
    const field = document.createElement('input');
    field.type = 'text';
    field.className = 'input-native archive-other-input';
    field.placeholder = '{onedrive}/… — or paste an absolute path';
    field.setAttribute('aria-label', 'Any other folder');
    const pickBtn = document.createElement('button');
    pickBtn.type = 'button';
    pickBtn.className = 'button-ghost folder-pick';
    pickBtn.setAttribute('aria-expanded', 'false');
    pickBtn.innerHTML = icon('search') + '<span class="folder-pick-label">Pick from index</span>';
    const go = document.createElement('button');
    go.type = 'button';
    go.className = 'button-surface archive-other-go';
    go.textContent = isFiled(item) ? 'Move here' : 'Archive here';
    go.addEventListener('click', function () {
      const typed = field.value.trim();
      if (!typed) { toast('Name a folder first', 'error'); return; }
      runAction(go, function () { return moveItem(item, typed, hint.value.trim(), false); });
    });
    other.append(field, pickBtn, go);
    body.appendChild(other);

    const picker = document.createElement('div');
    picker.className = 'folder-picker archive-picker';
    picker.hidden = true;
    body.appendChild(picker);
    pickBtn.addEventListener('click', function () {
      picker.hidden = !picker.hidden;
      pickBtn.setAttribute('aria-expanded', picker.hidden ? 'false' : 'true');
      if (picker.hidden) return;
      mountFolderPicker(picker, {
        onPick: function (ref) { field.value = ref; picker.hidden = true; pickBtn.setAttribute('aria-expanded', 'false'); },
        onClose: function () { pickBtn.setAttribute('aria-expanded', 'false'); },
      });
    });

    body.appendChild(hint);
    return { toggle: toggle, body: body };
  }

  function sameFolder(a, b) {
    if (!a || !b) return false;
    const norm = function (p) { return String(p).replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLowerCase(); };
    return norm(a) === norm(b);
  }

  /** The buttons one row offers, and (when it can be moved) the panel that
   *  goes with them. `onToggle` lets the grid show/hide the extra row the
   *  panel lives in. */
  function actionsFor(item, hooks) {
    const wrap = document.createElement('div');
    wrap.className = 'archive-row-actions';
    if (REVIEWABLE.indexOf(item.status) >= 0) {
      wrap.appendChild(actionButton('check', 'Accept', function () { return acceptItem(item, null); }));
    }
    let body = null;
    if (canMove(item)) {
      const panel = movePanel(item, hooks);
      wrap.appendChild(panel.toggle);
      body = panel.body;
    }
    if (isFiled(item)) {
      wrap.appendChild(actionButton('rotate-ccw', 'Revert', function () { return revertItem(item); }));
    }
    if (!wrap.childElementCount) {
      const none = document.createElement('span');
      none.className = 'muted';
      // A reverted mail is back in the Inbox and free to be filed by the next
      // run; there is deliberately nothing to press here.
      none.textContent = item.status === 'reverted' ? 'back in the Inbox' : '–';
      wrap.appendChild(none);
    }
    return { el: wrap, body: body };
  }

  // -------------------------------------------------------- the two drawings
  const COLUMNS = ['Subject', 'From', 'Sent', 'Destination', 'Files', 'Confidence', 'Why', 'State', ''];

  function renderTable(items) {
    const wrap = document.createElement('div');
    wrap.className = 'card table-wrap archive-table-wrap';
    const scroll = document.createElement('div');
    scroll.className = 'table-scroll';
    const table = document.createElement('table');
    table.className = 'task-table archive-table';
    const thead = document.createElement('thead');
    const hrow = document.createElement('tr');
    COLUMNS.forEach(function (label) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = label;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    const tbody = document.createElement('tbody');
    items.forEach(function (item) {
      const tr = document.createElement('tr');
      tr.className = 'archive-row';
      tr.dataset.id = String(item.id);
      tr.dataset.status = item.status;
      // The panel's own full-width row, right under this one, so opening it
      // never changes a single column's width.
      const panelRow = document.createElement('tr');
      panelRow.className = 'archive-move-row';
      panelRow.dataset.id = String(item.id);
      panelRow.hidden = true;
      const actions = actionsFor(item, {
        onToggle: function (open) { panelRow.hidden = !open; },
      });
      tr.append(
        cell('c-subject', subjectEl(item)),
        cell('c-sender', textEl(item.sender || '–')),
        cell('c-sent', textEl(item.sent_at ? fmtTsShort(item.sent_at) : '–')),
        cell('c-dest', destinationEl(item)),
        cell('c-files', filesEl(item)),
        cell('c-conf', confidenceEl(item)),
        cell('c-why', reasonEl(item)),
        cell('c-state', stateChip(item)),
        cell('c-act', actions.el)
      );
      tbody.appendChild(tr);
      if (!actions.body) return;
      const td = document.createElement('td');
      td.colSpan = COLUMNS.length;
      td.appendChild(actions.body);
      panelRow.appendChild(td);
      tbody.appendChild(panelRow);
    });
    table.append(thead, tbody);
    scroll.appendChild(table);
    wrap.appendChild(scroll);
    return wrap;
  }

  function cell(cls, child) {
    const td = document.createElement('td');
    td.className = cls;
    td.appendChild(child);
    return td;
  }

  function textEl(text) {
    const s = document.createElement('span');
    s.className = 'archive-text';
    s.textContent = text;
    s.title = text;
    return s;
  }

  function subjectEl(item) {
    const s = document.createElement('span');
    s.className = 'archive-subject';
    s.textContent = item.subject || '(no subject)';
    s.title = (item.subject || '(no subject)') + ' · ' + item.message_id;
    return s;
  }

  /** Phone: one card per mail, the actions behind the row's own disclosure —
   *  nine columns do not fit 390 px and a horizontal scroller hides the
   *  actions, which are the point of the screen. */
  function renderCards(items) {
    const list = document.createElement('div');
    list.className = 'archive-cards';
    items.forEach(function (item) {
      const card = document.createElement('article');
      card.className = 'card archive-card';
      card.dataset.id = String(item.id);
      card.dataset.status = item.status;

      const head = document.createElement('div');
      head.className = 'archive-card-head';
      head.append(subjectEl(item), stateChip(item));

      const meta = document.createElement('div');
      meta.className = 'archive-card-meta muted';
      meta.textContent = (item.sender || '–') + ' · ' + (item.sent_at ? fmtTsShort(item.sent_at) : '–');

      const dest = document.createElement('div');
      dest.className = 'archive-card-dest';
      dest.append(destinationEl(item), confidenceEl(item), filesEl(item));

      const why = document.createElement('p');
      why.className = 'archive-card-why muted';
      why.appendChild(reasonEl(item));

      const menu = document.createElement('details');
      menu.className = 'archive-menu';
      const summary = document.createElement('summary');
      summary.className = 'archive-menu-summary';
      summary.textContent = 'Review';
      const actions = actionsFor(item);
      menu.append(summary, actions.el);
      if (actions.body) menu.appendChild(actions.body);

      card.append(head, meta, dest, why, menu);
      list.appendChild(card);
    });
    return list;
  }

  function renderReport() {
    els.host.replaceChildren();
    if (status && !status.configured) {
      els.host.appendChild(emptyCard('archive', status.reason || 'Batch archiving is not configured here'));
      els.acceptAll.hidden = true;
      return;
    }
    if (!run) {
      els.host.appendChild(emptyCard('archive', runs.length ? 'Pick a run above' : 'No run yet — press “Archive Inbox now”'));
      els.acceptAll.hidden = true;
      return;
    }
    const items = run.items || [];
    if (!items.length) {
      els.host.appendChild(emptyCard('archive', run.status === 'running'
        ? 'The run has started — mails appear as they are decided'
        : 'This run touched no mail'));
      els.acceptAll.hidden = true;
      return;
    }
    const phone = window.matchMedia(PHONE_MQ).matches;
    els.host.appendChild(phone ? renderCards(items) : renderTable(items));
    const pending = items.filter(function (i) {
      return REVIEWABLE.indexOf(i.status) >= 0 && !i.decided_at;
    });
    els.acceptAll.hidden = pending.length === 0;
    els.acceptAll.textContent = 'Accept all ' + pending.length + ' that need you';
    els.acceptAll.dataset.ids = pending.map(function (i) { return i.id; }).join(',');
  }

  function emptyCard(glyph, message) {
    const card = document.createElement('div');
    card.className = 'card empty-card';
    card.appendChild(emptyStateEl(glyph, message));
    return card;
  }

  // ------------------------------------------------------------- loading
  async function refreshStatus() {
    try {
      status = (await api('/api/status')).archive || null;
    } catch (_) {
      status = null;     // unknown, which is not "off"
    }
    renderHead();
    opts.onStatus(status);
  }

  async function loadRuns() {
    try {
      runs = (await api('/api/archive/runs?limit=' + RUNS_LIMIT)).runs || [];
    } catch (err) {
      runs = [];
      toast(err.message || 'Could not read the archive runs', 'error');
    }
    renderPicker();
    renderRecent();
  }

  async function loadRun() {
    if (runId == null) { run = null; renderReport(); return; }
    try {
      run = await api('/api/archive/runs/' + runId);
    } catch (err) {
      run = null;
      toast(err.message || 'Could not read that run', 'error');
    }
    renderReport();
  }

  /** Everything this pane shows, in one pass — after an action, after a run. */
  async function reload() {
    await Promise.all([refreshStatus(), loadRuns()]);
    await loadRun();
    opts.onChanged();
  }

  /** The pane was opened (or a run was started elsewhere): read it all, and
   *  pick the poll back up when the service says a run is in flight. */
  async function refresh() {
    await Promise.all([refreshStatus(), loadRuns()]);
    await loadRun();
    if (status && status.running && !polling) startPolling();
  }

  // --------------------------------------------------------------- the run
  function progressText(r) {
    if (!r) return '';
    if (r.status === 'running') return 'running… ' + counts(r);
    return r.status === 'failed' ? 'failed — ' + (r.error || 'no reason recorded') : 'done · ' + counts(r);
  }

  function startPolling() {
    window.clearTimeout(poll);
    polling = true;
    poll = window.setTimeout(tick, POLL_MS);
    els.run.disabled = true;
    els.limit.disabled = true;
    els.runLabel.textContent = 'Archiving…';
  }

  async function tick() {
    poll = 0;
    try {
      if (runId == null) { const list = await api('/api/archive/runs?limit=1'); runId = (list.runs[0] || {}).id; }
      run = await api('/api/archive/runs/' + runId);
    } catch (err) {
      polling = false;
      els.progress.textContent = 'lost contact with the run — ' + (err.message || 'unknown');
      await refreshStatus();
      return;
    }
    els.progress.textContent = progressText(run);
    renderReport();
    if (run.status === 'running') { startPolling(); return; }
    polling = false;
    toast(run.status === 'failed'
      ? 'Archive run failed — ' + (run.error || 'see the report')
      : 'Archive run done · ' + counts(run), run.status === 'failed' ? 'error' : 'success');
    await Promise.all([refreshStatus(), loadRuns()]);
    renderPicker();
    renderReport();
    opts.onChanged();
  }

  async function startRun() {
    if (busy || (status && status.running)) return;
    const raw = els.limit.value.trim();
    const limit = raw === '' ? null : Number(raw);
    if (limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 1000)) {
      toast('“First N mails” takes a whole number from 1 to 1000, or nothing for the whole Inbox', 'error');
      return;
    }
    busy = true;
    els.run.disabled = true;
    els.progress.textContent = 'starting…';
    try {
      const started = await api('/api/archive/run', { method: 'POST', body: limit === null ? {} : { limit: limit } });
      runId = started.id;
      run = Object.assign({}, started, { items: [] });
      await loadRuns();
      els.pick.value = String(runId);
      els.progress.textContent = progressText(run);
      renderReport();
      startPolling();
    } catch (err) {
      // 409 archive_in_flight is the honest answer to a second click, and the
      // API's own sentence is better than anything invented here.
      els.progress.textContent = '';
      toast(err.message || 'Could not start the run', 'error');
      await refreshStatus();
    } finally {
      busy = false;
    }
  }

  // ------------------------------------------------------------------ wiring
  els.run.addEventListener('click', function () { startRun(); });
  els.pick.addEventListener('change', function () {
    runId = Number(els.pick.value) || null;
    loadRun();
  });
  els.acceptAll.addEventListener('click', function () {
    const ids = String(els.acceptAll.dataset.ids || '').split(',').filter(Boolean);
    if (!ids.length) return;
    runAction(els.acceptAll, async function () {
      const ok = await confirmDialog({
        title: 'Accept ' + ids.length + ' row(s)?',
        lines: [
          'They stay exactly where they are — this only records that you have seen them.',
          'Each one that has a folder also teaches the next run that the folder was right.',
        ],
        action: 'Accept them',
      });
      if (!ok) return;
      let failed = 0;
      for (const id of ids) {
        try {
          await api('/api/archive/items/' + id + '/accept', { method: 'POST', body: {} });
        } catch (_) { failed += 1; }
      }
      toast(failed
        ? (ids.length - failed) + ' accepted · ' + failed + ' refused'
        : ids.length + ' row(s) accepted', failed ? 'error' : 'success');
    });
  });
  const phoneMq = window.matchMedia(PHONE_MQ);
  if (phoneMq.addEventListener) phoneMq.addEventListener('change', function () { renderReport(); });

  return { refresh: refresh, refreshStatus: refreshStatus };
}
