/* task-os — one paint of the drawer body (the order is explained in
 * drawer.js). The blocks are siblings in one grid, so the stylesheet can lay
 * them out as one column (phone, the 440px panel) or as content beside
 * properties (a wide drawer) without a second renderer. */

'use strict';

import { activitySection } from './activity.js';
import { commentComposer, commentsSection } from './comments.js';
import { descriptionSection } from './description.js';
import { dueBlock, statusSegment } from './fields.js';
import { renderHead, renderTitleRow } from './head.js';
import { moreSection } from './more.js';
import { propsSection } from './props.js';

/** The drawer is a full-screen sheet below this width (styles/drawer.css),
 *  and there the comment field is pinned to its foot. */
export const SHEET_QUERY = '(max-width: 1023px)';

export function renderDrawer(ctx) {
  const t = ctx.current;
  ctx.el.innerHTML = '';
  if (!t) return;
  const pinned = window.matchMedia(SHEET_QUERY).matches;
  const body = document.createElement('div');
  body.className = 'drawer-body';
  body.append(
    statusSegment(ctx, t),
    dueBlock(ctx, t),
    commentsSection(ctx, t, pinned),
    propsSection(ctx, t),
    descriptionSection(ctx, t),
    moreSection(ctx, t),
    activitySection(ctx, t));
  // Last in the grid, so `position: sticky` holds it to the sheet's foot.
  if (pinned) body.appendChild(commentComposer(ctx, t, true));
  ctx.el.classList.toggle('has-pinned-composer', pinned);
  ctx.el.append(renderHead(ctx, t), renderTitleRow(ctx, t), body);
}
