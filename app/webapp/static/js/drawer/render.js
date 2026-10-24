/* task-os — one paint of the drawer body, top to bottom (the order is
 * explained in drawer.js). */

'use strict';

import { PRIORITIES, relDue } from '../../format.js';
import { activitySection } from './activity.js';
import { commentsSection } from './comments.js';
import { descriptionSection } from './description.js';
import { dateField, memberName, quickMoves, selectField, statusField } from './fields.js';
import { deleteFoot } from './foot.js';
import { renderHead, renderTitleRow } from './head.js';
import { linkPills } from './links.js';
import { moreSection } from './more.js';

/** Due first, with its quick moves, then status and priority (and owner). */
function mainFields(ctx, t) {
  const fields = document.createElement('div');
  fields.className = 'drawer-fields drawer-fields-main';
  fields.appendChild(dateField(ctx, t, 'due', 'Due', relDue(t.due).text));
  fields.appendChild(quickMoves(ctx));
  fields.appendChild(statusField(ctx, t));
  fields.appendChild(selectField(ctx, 'Priority', 'priority', PRIORITIES, t.priority));
  // Whose task it is (#476) — beside status and priority, never under More
  // fields, so handing a task over is one pick on the phone too. One member
  // has nobody to hand it to, so there is no control.
  const members = ctx.opts.members() || [];
  if (members.length > 1) {
    fields.classList.add('has-owner');
    fields.appendChild(selectField(ctx, 'Owner', 'owner', members.map(function (m) { return m.id; }), t.owner, function (id) { return memberName(ctx, id); }));
  }
  return fields;
}

export function renderDrawer(ctx) {
  const t = ctx.current;
  ctx.el.innerHTML = '';
  if (!t) return;
  ctx.el.append(
    renderHead(ctx, t),
    renderTitleRow(ctx, t),
    mainFields(ctx, t),
    linkPills(t),
    descriptionSection(ctx, t),
    commentsSection(ctx, t),
    activitySection(ctx, t),
    moreSection(ctx, t),
    deleteFoot(ctx, t));
}
