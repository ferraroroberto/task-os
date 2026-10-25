/* task-os — the drawer's activity log. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { fmtTs } from '../../format.js';
import { section } from './dom.js';
import { memberName } from './fields.js';

/** The issue sync's actor (src/issue_sync.py SYNC_ACTOR): its activity rows fold. */
const SYNC_ACTOR = 'sync';

function activityRow(ctx, a) {
  const row = document.createElement('div');
  row.className = 'activity-row';
  row.dataset.field = a.field;
  const change = document.createElement('span');
  change.className = 'activity-change';
  // One weight for the whole line — the field name is set apart by color
  // only (uniform-weight feedback).
  const f = document.createElement('span');
  f.className = 'activity-field';
  f.textContent = a.field;
  change.appendChild(f);
  change.appendChild(document.createTextNode(' '));
  const oldV = document.createElement('span');
  oldV.className = 'activity-old';
  // an owner is stored as a member id; the log reads it as the name
  const shown = a.field === 'owner' ? function (id) { return memberName(ctx, id); } : function (v) { return v; };
  oldV.textContent = a.old_value == null ? '∅' : shown(a.old_value);
  const arrow = document.createElement('span');
  arrow.className = 'activity-arrow';
  arrow.innerHTML = ' ' + icon('arrow-right') + ' ';
  const newV = document.createElement('span');
  newV.className = 'activity-new';
  newV.textContent = a.new_value == null ? '∅' : shown(a.new_value);
  change.append(oldV, arrow, newV);
  const meta = document.createElement('span');
  meta.className = 'activity-meta';
  meta.textContent = a.actor + ' · ' + fmtTs(a.ts);
  meta.title = a.ts;
  row.append(change, meta);
  return row;
}

/** The log, newest first. The issue sync writes most of it on a synced task
 *  (85% of all activity), so its rows fold behind one toggle and the
 *  owner's own changes lead. */
export function activitySection(ctx, t) {
  const activity = section('activity', 'Activity', 'activity');
  const alist = document.createElement('div');
  alist.className = 'activity-list';
  const all = t.activity || [];
  const synced = all.filter(function (a) { return a.actor === SYNC_ACTOR; }).length;
  all.forEach(function (a) {
    if (a.actor === SYNC_ACTOR && !ctx.syncShown) return;
    alist.appendChild(activityRow(ctx, a));
  });
  activity.appendChild(alist);
  if (synced) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'button-ghost activity-sync-toggle';
    toggle.setAttribute('aria-expanded', String(ctx.syncShown));
    toggle.textContent = ctx.syncShown
      ? 'Hide sync updates'
      : 'Show ' + synced + ' sync update' + (synced === 1 ? '' : 's');
    toggle.addEventListener('click', function () { ctx.syncShown = !ctx.syncShown; ctx.render(); });
    activity.appendChild(toggle);
  }
  return activity;
}
