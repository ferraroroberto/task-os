/* task-os — the drawer's activity log. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { collapsibleCard } from '../../collapsible.js';
import { fmtTs } from '../../format.js';
import { memberName } from './fields.js';

/** The issue sync's actor (src/issue_sync.py SYNC_ACTOR): its activity rows fold. */
const SYNC_ACTOR = 'sync';

/** A logged field key in the words the drawer's own fields use, so a stored
 *  column name (`folder_ref`) never reads as ordinary text; the row keeps the
 *  key itself on `data-field`. */
const FIELD_WORDS = {
  recurrence: 'repeat',
  recurrence_anchor: 'repeat on',
  recurrence_interval: 'repeat every',
  folder_ref: 'folder',
  person_id: 'person',
};

/** The words for a field: the drawer's word where it has one, else the key
 *  with its underscores read as spaces. */
export function fieldWords(field) {
  return FIELD_WORDS[field] || String(field).replace(/_/g, ' ');
}

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
  f.textContent = fieldWords(a.field);
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

// Open or closed for the page's life, as More fields: a reload folds it again.
let activityOpen = false;

/** The log, newest first, folded behind its count: a long history must never
 *  push the fields out of reach. The issue sync writes most of it on a synced
 *  task (85% of all activity), so its rows fold behind one more toggle and
 *  the owner's own changes lead. */
export function activitySection(ctx, t) {
  const n = (t.activity || []).length;
  const card = collapsibleCard({
    className: 'disclosure-flat drawer-activity', icon: 'activity', title: 'Activity',
    count: n ? n + (n === 1 ? ' change' : ' changes') : 'none yet', countClass: 'drawer-activity-hint',
  });
  card.card.open = activityOpen;
  card.card.addEventListener('toggle', function () { activityOpen = card.card.open; });
  const activity = card.body;
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
    toggle.dataset.track = 'drawer.activity-sync-toggle';
    toggle.type = 'button';
    toggle.className = 'button-ghost activity-sync-toggle';
    toggle.setAttribute('aria-expanded', String(ctx.syncShown));
    toggle.textContent = ctx.syncShown
      ? 'Hide sync updates'
      : 'Show ' + synced + ' sync update' + (synced === 1 ? '' : 's');
    toggle.addEventListener('click', function () { ctx.syncShown = !ctx.syncShown; ctx.render(); });
    activity.appendChild(toggle);
  }
  return card.card;
}
