/* task-os — the shared writes: AI triage and its suggestions, one task's
 * status / due / parent, the Select bar's bulk change and delete, and the
 * task behind a row. Each takes the app composer's `app` first (app.js) and
 * ends in `app.refreshAll()`, so the views never drift.
 */

'use strict';

import { actionById, failedOf, failureText } from '../../actions.js';
import { api } from '../../api.js';
import { confirmDialog } from '../../confirm.js';
import * as selection from '../../selection.js';
import { toast } from '../../toast.js';

export async function triageInbox(app) {
  if (app.state.triaging) return;
  app.state.triaging = true;
  app.renderBoardPane();
  try {
    const result = await api('/api/ai/triage', { method: 'POST', body: {} });
    app.indexSuggestions(result.items);
    toast('AI triage: ' + result.items.length + ' suggestion(s) staged', 'success');
  } catch (err) {
    toast(err.message || 'AI triage failed', 'error');
    try {
      const status = await api('/api/status');
      app.state.ai = status.ai || app.state.ai;
    } catch (_) { /* the triage error is already visible */ }
    throw err;
  } finally {
    app.state.triaging = false;
    app.renderBoardPane();
  }
}

export async function acceptAISuggestion(app, suggestionId) {
  try {
    const result = await api('/api/ai/suggestions/' + suggestionId + '/accept', {
      method: 'POST', body: {},
    });
    delete app.state.aiSuggestions[result.suggestion.task_id];
    await app.refreshAll();
    toast('Suggestion accepted — moved to Todo', 'success');
  } catch (err) {
    toast(err.message || 'Could not accept the suggestion', 'error');
    throw err;
  }
}

export async function rejectAISuggestion(app, suggestionId) {
  try {
    const result = await api('/api/ai/suggestions/' + suggestionId + '/reject', {
      method: 'POST', body: {},
    });
    delete app.state.aiSuggestions[result.task_id];
    app.renderBoardPane();
    toast('Suggestion rejected', 'success');
  } catch (err) {
    toast(err.message || 'Could not reject the suggestion', 'error');
    throw err;
  }
}

// ---------------------------------------------------------------- writes
export async function patchTask(app, id, changes) {
  try {
    await api('/api/tasks/' + id, { method: 'PATCH', body: changes });
  } catch (err) {
    toast(err.message || 'Update failed', 'error');
    throw err;
  }
  await app.refreshAll();
  if (app.drawer.currentId() === id) app.drawer.refresh();
}

/** The row's status select (and the drawer's). Completing goes through the
 *  one action runner — the same write, toast and Undo as the `e` key:
 *  "complete" (recurring tasks only — see rows.js::statusOptions) rolls the
 *  due one cadence forward instead of closing, and "done" on a task that does
 *  not recur is the same close. "done" on a recurring task stays a plain
 *  PATCH — closed for good, off the series — as does every other
 *  status. */
export async function setStatus(app, id, status) {
  const task = status === 'complete' || status === 'done' ? await app.resolveTask(id) : null;
  const completes = status === 'complete' || (status === 'done' && task && !task.recurrence);
  if (!completes) return app.patchTask(id, { status: status });
  if (!task) {
    toast('That task is no longer on the list', 'error');
    throw new Error('task not found');
  }
  // Another row action still writing: refuse rather than queue, so the
  // select puts its old value back instead of claiming a change.
  if (!(await app.actions.run(actionById('complete'), [task]))) throw new Error('busy');
}

/** A row dropped on a Board week lane: re-dated to the lane's first
 *  day through the one action runner — the date sheet's own Move, so the same
 *  write, toast and Undo, and nothing but `due` (`null` stays the sheet's
 *  "No date", which no lane drops). */
export async function setDue(app, id, due) {
  const task = await app.resolveTask(id);
  if (!task) {
    toast('That task is no longer on the list', 'error');
    throw new Error('task not found');
  }
  if (!(await app.actions.run(actionById('change-date'), [task], due))) throw new Error('busy');
}

/** Delete every ticked task — POST /api/tasks/bulk/delete, after the
 *  one confirmation names the count, the projects whose children go too and
 *  the synced coding tasks the next sync would bring back. Per-id results as
 *  the bulk change: what failed is named and stays ticked; a clean batch
 *  clears the selection but stays in Select mode. */
export async function bulkDelete(app) {
  const ids = selection.selectedIds();
  if (!ids.length) return;
  const known = ids.map(function (id) {
    return app.state.items.find(function (t) { return t.id === id; });
  }).filter(Boolean);
  const projects = known.filter(function (t) { return t.child_count > 0; }).length;
  const coding = known.filter(function (t) { return t.issue_ref && t.issue_ref.state === 'open'; }).length;
  const ok = await confirmDialog({
    title: 'Delete ' + ids.length + ' task' + (ids.length === 1 ? '' : 's') + '?',
    lines: [
      projects
        ? (projects === 1 ? 'One of them is a project — its' : projects + ' of them are projects — their') + ' child tasks go too.'
        : null,
      'This cannot be undone: the tasks, their comments, links and history are removed.',
    ],
    warn: coding
      ? (coding === 1 ? 'One is a synced coding task that' : coding + ' are synced coding tasks that') + ' the next issue sync recreates while the issue stays open. Unlink first, or close the issue.'
      : null,
    action: 'Delete',
  });
  if (!ok) return;
  let res;
  try {
    res = await api('/api/tasks/bulk/delete', { method: 'POST', body: { ids: ids } });
  } catch (err) {
    toast(err.message || 'Delete failed', 'error');
    throw err;
  }
  const failed = failedOf(res.results);
  if (!failed.length) {
    toast(res.deleted + ' task' + (res.deleted === 1 ? '' : 's') + ' deleted', 'success');
    selection.clear();
  } else {
    toast(failureText(res.deleted, 'deleted', failed), 'error');
    selection.keepOnly(new Set(failed.map(function (f) { return f.id; })));
  }
  if (app.drawer.currentId() != null && ids.indexOf(app.drawer.currentId()) >= 0) app.closeTask();
  await app.refreshAll();
}

/** Apply one change to every ticked task — POST /api/tasks/bulk.
 *
 *  The response is per id, because a batch is not all-or-nothing: an id
 *  deleted in another tab 404s while the rest apply. What failed is named in
 *  the toast and stays ticked, so a retry is one click — unless the task is
 *  genuinely gone, which the refresh's prune then drops (there is nothing to
 *  retry). A clean batch clears the selection but stays in Select mode, ready
 *  for the next pick.
 *  `status: 'complete'` carries the recurring-task roll, exactly as the row
 *  select's option does — the server owns what it means per task. */
export async function bulkApply(app, changes) {
  const ids = selection.selectedIds();
  if (!ids.length) return;
  let res;
  try {
    res = await api('/api/tasks/bulk', { method: 'POST', body: Object.assign({ ids: ids }, changes) });
  } catch (err) {
    toast(err.message || 'Bulk change failed', 'error');
    throw err;
  }
  const failed = failedOf(res.results);
  if (!failed.length) {
    toast(res.updated + ' task' + (res.updated === 1 ? '' : 's') + ' updated', 'success');
    selection.clear();
  } else {
    toast(failureText(res.updated, 'updated', failed), 'error');
    selection.keepOnly(new Set(failed.map(function (f) { return f.id; })));
  }
  await app.refreshAll();
  if (app.drawer.currentId() != null && ids.indexOf(app.drawer.currentId()) >= 0) app.drawer.refresh();
  return res;
}

/** The task behind a row, for the keymap: the summary already on screen
 *  when there is one, else a fetch — a Search hit can be a task outside the
 *  filtered list, and undo needs that task's real prior values, not a guess. */
export async function resolveTask(app, id) {
  const n = Number(id);
  const local = app.state.items.concat(app.state.journal.items)
    .find(function (t) { return t.id === n; });
  if (local) return local;
  try { return await api('/api/tasks/' + n); } catch (_) { return null; }
}

export async function moveTask(app, id, parentId) {
  try {
    const t = await api('/api/tasks/' + id + '/move', { method: 'POST', body: { parent_id: parentId } });
    toast('Moved "' + t.title + '" ' + (parentId == null ? 'to the top level' : 'under ' + (t.breadcrumb.length ? t.breadcrumb[t.breadcrumb.length - 1].title : '#' + parentId)), 'success');
  } catch (err) {
    toast(err.message || 'Move failed', 'error');
    return;
  }
  await app.refreshAll();
  if (app.drawer.currentId() === id) app.drawer.refresh();
}
