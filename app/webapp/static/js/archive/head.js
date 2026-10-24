/* task-os — Settings → Email archiving: the sheet's head (the service's state,
 * the last run, what the picker's runs add up to) and the run picker. */

'use strict';

import { fmtTsShort, modelName, pct, statusPart } from '../../format.js';
import { counts, outcomes } from './text.js';

/** `09/09 01:03` — the head's compact stamp: the locale's own day/month
 *  order, no year, and a 24-hour clock, because `9/9/26, 1:03 AM` is 30px of
 *  a line that has none to spare. The whole reading stays in the row title. */
function stampShort(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return fmtTsShort(iso);
  // The locale decides the order and the separator; the padding is ours,
  // because ICU resolves a day+month-only skeleton to whichever pattern the
  // locale has and can hand back `9/9` where `09/09` was asked for.
  const day = new Intl.DateTimeFormat(undefined, { day: '2-digit', month: '2-digit' })
    .formatToParts(d)
    .map(function (part) {
      return part.type === 'literal' ? part.value : String(part.value).padStart(2, '0');
    })
    .join('');
  return day + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

function pad2(n) {
  return String(n).padStart(2, '0');
}

/**
 * Draw a run's one-line summary into `el` — the single formatter of it (#262):
 * since #397 the sheet's head is the one place a run's summary is shown (the
 * Settings card that repeated it is gone). `last` is the API's run row
 * (`status.last_run`); `null` is "never run". `narrow` picks the one-line
 * phone wording.
 * @param {HTMLElement} el
 * @param {object|null} last
 * @param {boolean} narrow
 */
function renderRunSummary(el, last, narrow) {
  el.replaceChildren();
  el.classList.remove('muted');
  if (!last) { el.textContent = 'never'; return; }
  const at = last.finished_at || last.started_at;
  el.append(
    narrow ? stampShort(at) : fmtTsShort(at), ' · ',
    statusPart(last.status === 'failed' || last.status === 'running' ? 'warn' : 'ok', last.status),
    ' · ' + (narrow ? outcomes(last) : counts(last))
  );
  if (last.agreement != null) {
    el.append(narrow
      ? ' · ' + pct(last.agreement) + ' agreed'
      : ' · model agreed with the suggester on ' + pct(last.agreement));
  }
  if (last.error) el.append(' · ' + last.error);
}

/** `3 runs`, `1 run` — the head's short wording says the number and the noun,
 *  never `run(s)`, which reads as an unfinished sentence on a phone. */
function plural(n, word) {
  return n + ' ' + word + (n === 1 ? '' : 's');
}

export function renderHead(ctx) {
  drawHead(ctx);
  titleHeadRows(ctx);
}

/** The service's own state. Off always carries its reason; a failed status
 *  call is "unknown", which is not the same as "off". */
function drawHead(ctx) {
  const els = ctx.els;
  const status = ctx.st.status;
  els.status.replaceChildren();
  els.status.classList.remove('muted');
  els.recentLabel.textContent = ctx.narrow() ? 'Recent' : 'Recent runs';
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
    els.status.append(statusPart(status.last_error ? 'warn' : 'ok', status.running ? 'running' : 'ready'));
    if (ctx.narrow()) {
      els.status.append(
        ' · ' + (status.model ? modelName(status.model) : 'no model')
        + ' · ' + status.batch_size + ' a batch · ' + status.examples + ' remembered'
      );
    } else {
      els.status.append(
        ' · ' + (status.model ? 'sorted by ' + modelName(status.model) : 'no model')
        + ' · ' + status.batch_size + ' mails a batch · ' + status.examples + ' corrections remembered'
      );
    }
    if (status.last_error) els.status.append(' · last error: ' + status.last_error);
    els.run.disabled = ctx.st.busy || !!status.running;
    els.limit.disabled = els.run.disabled;
  }
  els.runLabel.textContent = status && status.running ? 'Archiving…' : 'Archive Inbox now';
  renderRunSummary(els.lastRun, status.last_run, ctx.narrow());
}

/** What the runs on the picker add up to. Derived from the run rows on
 *  screen and named as such — never presented as an all-time accept rate,
 *  which nothing here measures. */
export function renderRecent(ctx) {
  drawRecent(ctx);
  titleHeadRows(ctx);
}

function drawRecent(ctx) {
  const recent = ctx.els.recent;
  recent.replaceChildren();
  recent.classList.remove('muted');
  const done = ctx.st.runs.filter(function (r) { return r.status !== 'running'; });
  if (!done.length) { recent.textContent = 'no finished run yet'; return; }
  const total = done.reduce(function (a, r) { return a + (r.planned || 0); }, 0);
  const filed = done.reduce(function (a, r) { return a + (r.archived || 0); }, 0);
  const review = done.reduce(function (a, r) { return a + (r.needs_review || 0); }, 0);
  if (ctx.narrow()) {
    recent.append(
      plural(done.length, 'run') + ' · ' + plural(total, 'mail') + ' · ' + filed + ' filed'
    );
    if (total) recent.append(' · ' + pct(filed / total) + ' straight away');
    return;
  }
  recent.append(
    done.length + ' run(s) · ' + total + ' mail(s) · ' + filed + ' filed · ' + review + ' needed you'
  );
  if (total) recent.append(' (' + pct(filed / total) + ' filed straight away)');
}

export function renderPicker(ctx) {
  const st = ctx.st;
  const pick = ctx.els.pick;
  pick.replaceChildren();
  if (!st.runs.length) {
    const o = document.createElement('option');
    o.textContent = 'no runs yet';
    pick.appendChild(o);
    pick.disabled = true;
    return;
  }
  pick.disabled = false;
  st.runs.forEach(function (r) {
    const o = document.createElement('option');
    o.value = String(r.id);
    o.textContent = '#' + r.id + ' · ' + fmtTsShort(r.started_at) + ' · ' + r.status
      + ' · ' + (r.planned || 0) + ' mail(s)';
    pick.appendChild(o);
  });
  if (st.runId == null || !st.runs.some(function (r) { return r.id === st.runId; })) st.runId = st.runs[0].id;
  pick.value = String(st.runId);
}

/** The narrow head draws one line per reading and ellipsizes what does not
 *  fit, so the whole reading has to stay reachable somewhere — the title,
 *  never nowhere. Called after every head render, once the text is in. */
function titleHeadRows(ctx) {
  const els = ctx.els;
  [els.status, els.lastRun, els.recent].forEach(function (el) {
    if (ctx.narrow()) el.title = el.textContent;
    else el.removeAttribute('title');
  });
}
