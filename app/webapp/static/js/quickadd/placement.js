/* task-os — quick-add: where the task lives and whose it is. The Project and
 * Owner selects are filled from the app's own lists each time the dialog opens
 * (a project made since the last open is there) and read back by the submit. */

'use strict';

import { CLOSED_STATUSES } from '../tasks/status.js';

const NO_PROJECT = '';

/** The projects a new task can go under: a closed one gathers nothing new. */
function openProjects(ctx) {
  return (ctx.opts.projects() || []).filter(function (p) { return CLOSED_STATUSES.indexOf(p.status) < 0; });
}

function option(value, label) {
  const o = document.createElement('option');
  o.value = String(value);
  o.textContent = label;
  return o;
}

/** Fill both selects and set their defaults: the project the list is filtered
 *  to (else none), the owner the viewer is (else the install's first member).
 *  A single-member install has nobody to hand a task to, so no Owner row. */
export function fillPlacement(ctx) {
  const { project, owner, ownerRow } = ctx.els;
  project.textContent = '';
  project.appendChild(option(NO_PROJECT, '— none —'));
  openProjects(ctx).forEach(function (p) {
    project.appendChild(option(p.id, '  '.repeat(p.depth || 0) + p.title));
  });
  const filtered = String(ctx.opts.defaultProject() || NO_PROJECT);
  project.value = Array.prototype.some.call(project.options, function (o) { return o.value === filtered; })
    ? filtered : NO_PROJECT;

  const members = ctx.opts.members() || [];
  owner.textContent = '';
  members.forEach(function (m) { owner.appendChild(option(m.id, m.name)); });
  ownerRow.hidden = members.length < 2;
  const viewer = ctx.opts.viewer();
  const known = members.some(function (m) { return m.id === viewer; });
  if (members.length) owner.value = known ? viewer : members[0].id;
}

/** The fields the create body gains: a parent when a project is picked, an
 *  owner only when the Owner row is shown (the server's own default — the
 *  viewer — covers the rest). */
export function placementBody(ctx) {
  const { project, owner, ownerRow } = ctx.els;
  const body = {};
  if (project.value !== NO_PROJECT) body.parent_id = Number(project.value);
  if (!ownerRow.hidden && owner.value) body.owner = owner.value;
  return body;
}
