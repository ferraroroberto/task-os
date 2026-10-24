/* task-os — the drawer's More fields: the rarely used fields and editors
 * (#394, decision 7), one disclosure. */

'use strict';

import { collapsibleCard } from '../../collapsible.js';
import { isDeferred, relDue } from '../../format.js';
import { RECURRENCES, anchorOptions } from '../../recurrence.js';
import { anchorField, dateField, intervalField, selectField, textField } from './fields.js';
import { folderSection } from './folder.js';
import { renderIssuePanel } from './issue.js';
import { linksSection } from './links.js';
import { blockedBySection, childrenSection } from './relations.js';

// More fields stays as the owner left it for the page's life, across every
// task and every re-render a write causes; a reload closes it again (#394).
let moreOpen = false;

/** What More fields holds that is set, so its summary says it while closed. */
function moreHint(ctx, t) {
  const parts = [];
  if (isDeferred(t)) parts.push('starts ' + relDue(t.starts).text);
  if (t.recurrence) parts.push('repeats');
  if (t.person_id != null) {
    const p = (ctx.opts.people() || []).find(function (x) { return x.id === t.person_id; });
    if (p) parts.push(p.name);
  }
  const blockers = (t.blocked_by || []).length;
  if (blockers) parts.push(blockers + (blockers === 1 ? ' blocker' : ' blockers'));
  const kids = (t.children || []).length;
  if (kids) parts.push(kids + (kids === 1 ? ' child' : ' children'));
  return parts.join(' · ');
}

/** The grid of single-field editors at the top of More fields. */
function moreFields(ctx, t) {
  const fields = document.createElement('div');
  fields.className = 'drawer-fields';
  fields.appendChild(dateField(ctx, t, 'starts', 'Starts',
    isDeferred(t) ? relDue(t.starts).text : 'passed'));
  // Repeat is a composer (#112): the cadence, then — once there is one — how
  // many of it to wait (#229), then — only for the cadences that can carry
  // one — the fixed day it lands on. Switching the cadence re-renders, and
  // the server has already dropped an anchor the new cadence cannot hold, so
  // the On select never shows a stale day.
  fields.appendChild(selectField(ctx, 'Repeat', 'recurrence', RECURRENCES, t.recurrence || '', function (v) { return v || 'never'; }));
  if (t.recurrence) fields.appendChild(intervalField(ctx, t));
  const anchorGroups = anchorOptions(t.recurrence);
  if (anchorGroups.length) fields.appendChild(anchorField(ctx, t, anchorGroups));
  const people = [{ id: '', name: '—' }].concat(ctx.opts.people() || []);
  fields.appendChild(selectField(ctx, 'Person', 'person_id', people.map(function (p) { return p.id; }), t.person_id == null ? '' : t.person_id, function (v) {
    const p = people.find(function (x) { return String(x.id) === String(v == null ? '' : v); });
    return p ? p.name : '—';
  }));
  fields.appendChild(textField(ctx, 'Code', 'code', t.code, 'optional'));
  return fields;
}

export function moreSection(ctx, t) {
  const more = collapsibleCard({
    className: 'disclosure-flat drawer-more', title: 'More fields',
    count: moreHint(ctx, t), countClass: 'drawer-more-hint',
  });
  more.card.open = moreOpen;
  more.card.addEventListener('toggle', function () { moreOpen = more.card.open; });
  more.body.append(
    moreFields(ctx, t),
    folderSection(ctx, t),        // Step 9
    linksSection(ctx, t),
    blockedBySection(ctx, t),     // #100
    childrenSection(ctx, t),
    renderIssuePanel(ctx, t));
  return more.card;
}
