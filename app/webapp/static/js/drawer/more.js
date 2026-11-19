/* task-os — the drawer's More fields: the rarely used fields and editors,
 * in one disclosure. */

'use strict';

import { collapsibleCard } from '../../collapsible.js';
import { isDeferred, relDue } from '../../format.js';
import { dateField, textField } from './fields.js';
import { renderIssuePanel } from './issue.js';
import { blockedBySection, childrenSection } from './relations.js';

// More fields stays as the owner left it for the page's life, across every
// task and every re-render a write causes; a reload closes it again.
let moreOpen = false;

/** What More fields holds that is set, so its summary says it while closed. */
function moreHint(t) {
  const parts = [];
  if (isDeferred(t)) parts.push('starts ' + relDue(t.starts).text);
  if (t.code) parts.push(t.code);
  const blockers = (t.blocked_by || []).length;
  if (blockers) parts.push(blockers + (blockers === 1 ? ' blocker' : ' blockers'));
  const kids = (t.children || []).length;
  if (kids) parts.push(kids + (kids === 1 ? ' child' : ' children'));
  return parts.join(' · ');
}

/** The single-field editors at the top of More fields. */
function moreFields(ctx, t) {
  const fields = document.createElement('div');
  fields.className = 'drawer-fields';
  fields.appendChild(dateField(ctx, t, 'starts', 'Starts',
    isDeferred(t) ? relDue(t.starts).text : 'passed'));
  fields.appendChild(textField(ctx, 'Code', 'code', t.code, 'optional'));
  return fields;
}

export function moreSection(ctx, t) {
  const more = collapsibleCard({
    className: 'disclosure-flat drawer-more', title: 'More fields',
    count: moreHint(t), countClass: 'drawer-more-hint',
  });
  more.card.open = moreOpen;
  more.card.addEventListener('toggle', function () { moreOpen = more.card.open; });
  more.body.append(
    moreFields(ctx, t),
    blockedBySection(ctx, t),
    childrenSection(ctx, t),
    renderIssuePanel(ctx, t));
  return more.card;
}
