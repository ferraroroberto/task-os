/* task-os — the ONE filter state every tab shares, and its sheet.
 *
 * Board, Today, Search and the journal are renderings of the same list, so
 * they read one filter state — this module owns its shape, its URL encoding
 * (`?status=todo&project=12&person=3,5&sort=updated` is the same shareable
 * view on every tab) and the controls that edit it:
 *
 *   <input class="filter-q">          the live text filter, always visible in
 *                                     the pane's own top strip; the
 *                                     list's count is its placeholder
 *   <button class="filter-open">      beside it: the filter glyph and how many
 *                                     settings are on
 *   <button class="filter-clear-all"> a × after it, there only while any are on:
 *                                     the sheet's Clear in one tap
 *   <dialog id="filterSheet">         what the button opens — the vendored
 *                                     editor modal, "Filters & sort": sort,
 *                                     the view toggles a tab brings (`views`),
 *                                     then status · project · person · due · modified;
 *                                     status and person are ticks in place
 *
 * Nothing about the state needs the sheet open to read: the count is on the
 * button, and the button's name says what is on in words. The text input is
 * built once, so a re-render never moves the caret.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { addDays, isBlocked, isDeferred, STATUSES, todayISO } from './format.js';
import { modalCard, onceClosed } from './modal.js';
import { CLOSED, SORTS, sortLabel } from './rows.js';

export const DEFAULT_FILTERS = { status: [], everyStatus: false, project: '', person: [], due: '', updated: '', q: '', sort: 'due', scope: 'mine', whose: 'mine', owners: [] };
/**
 * The Search tab's second status state. Search shows the open statuses ticked
 * by default (`status` empty), and clearing every tick there means every
 * status, done and cancelled included — a state `status: []` cannot also be, so
 * it is its own flag, written to the URL as the word `all`. Only Search reads
 * it: Today, Board and the journal keep reading "none ticked" as the open tasks.
 */
export const EVERY_STATUS = 'all';
/**
 * Which kind of task a list shows: the ones you
 * make, the issues the forge sync brings in, or both — labelled Tasks · Issues
 * · All, when "Mine" became the other axis (`WHOSE`). A task is an
 * issue when it carries an `issue_ref` — the coding task the sync made
 * (`coding` ⇔ issue_ref). One URL key, `scope`, absent for the default (its
 * id stays `mine`, so every saved `?scope=` link keeps working). On Today and
 * Board it is a row of the sheet (the tab's `views`, js/app/viewrows.js), counted
 * by `activeViewCount` and reset by Clear; on Search the segmented switch under
 * the box owns it (scope.js) and the sheet there neither counts nor resets it.
 */
export const SCOPES = [['mine', 'Tasks'], ['issues', 'Issues'], ['all', 'All']];
/**
 * Whose tasks a list shows: the viewer's own, every member's, or the members
 * picked on the person row (`owners`, member ids). A separate axis from
 * `SCOPES`, not folded into it. `whose` is Mine · Everyone and one URL key,
 * written only for Everyone (absent = Mine); the pick is also kept per device
 * under `WHOSE_KEY` and an explicit URL value wins over it. `owners` is the
 * several-allowed pick (made on the "+N more" sheet; the row itself is
 * single-choice): one URL key, `owner` (the contact filter owns
 * `person`), and while it is set it narrows the list in place of `whose`.
 * Like the scope they are rows of the Today and Board sheet, counted by
 * `activeViewCount` and reset by its Clear. The Search tab ignores them:
 * search covers everyone.
 */
export const WHOSE = [['mine', 'Mine'], ['everyone', 'Everyone']];
export const WHOSE_KEY = 'task-os.whose';
/**
 * The status multi-select's pseudo-value. Not a status: it flips the
 * list from the awake tasks to the sleeping ones (a `starts` date still in the
 * future), intersected with any real statuses ticked alongside it. The server
 * splits it back out in `app/webapp/routers/tasks.py`; `matchesFilters` below
 * applies the same rule to rows that never went through /api/tasks.
 */
export const DEFERRED = 'deferred';
/**
 * The status multi-select's second pseudo-value. Same shape as
 * `DEFERRED`: not a status, narrows the list to tasks with an open blocker,
 * intersected with any real statuses ticked alongside it. The server splits
 * it back out in `app/webapp/routers/tasks.py`; `matchesFilters` below
 * applies the same rule to rows that never went through /api/tasks.
 */
export const BLOCKED = 'blocked';
export const DUE_WINDOWS = [['', 'Any due date'], ['today', 'Due today'], ['week', 'Due this week'], ['overdue', 'Overdue']];
// The `stale*` windows are the inverse: untouched for MORE than N days.
// The boundary date is computed client-side — the API only ever sees a plain
// `updated_before=YYYY-MM-DD`, no relative magic server-side.
export const UPDATED_WINDOWS = [['', 'Modified any time'], ['today', 'Modified today'], ['week', 'Modified in 7 days'], ['month', 'Modified in 30 days'], ['stale30', 'Untouched > 30 days'], ['stale60', 'Untouched > 60 days'], ['stale90', 'Untouched > 90 days']];
const TEXT_DEBOUNCE_MS = 250;

function csv(value) {
  return (value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}

// ------------------------------------------------------------ URL state
/** The device's remembered whose pick: Everyone only when it says so, Mine for
 *  anything else — an empty, odd or unreadable store (private mode throws). */
export function storedWhose(storage) {
  try { return storage && storage.getItem(WHOSE_KEY) === 'everyone' ? 'everyone' : 'mine'; } catch (_) { return 'mine'; }
}

/**
 * @param {string} search  `location.search`
 * @param {string} [stored]  the device's remembered whose pick (`storedWhose`);
 *   used when the URL carries no `whose` key — an explicit one wins
 */
export function filtersFromSearch(search, stored) {
  const p = new URLSearchParams(search || '');
  const f = Object.assign({}, DEFAULT_FILTERS);
  const statusWords = csv(p.get('status'));
  f.status = statusWords.filter(function (s) { return STATUSES.indexOf(s) >= 0 || s === DEFERRED || s === BLOCKED; });
  f.everyStatus = statusWords.indexOf(EVERY_STATUS) >= 0;
  f.project = p.get('project') || '';
  f.person = csv(p.get('person')).filter(function (s) { return /^\d+$/.test(s); });
  f.due = DUE_WINDOWS.some(function (w) { return w[0] === p.get('due'); }) ? p.get('due') : '';
  f.updated = UPDATED_WINDOWS.some(function (w) { return w[0] === p.get('updated'); }) ? p.get('updated') : '';
  f.q = p.get('q') || '';
  f.sort = SORTS.some(function (s) { return s[0] === p.get('sort'); }) ? p.get('sort') : 'due';
  f.scope = SCOPES.some(function (s) { return s[0] === p.get('scope'); }) ? p.get('scope') : 'mine';
  const whose = p.get('whose');
  f.whose = WHOSE.some(function (w) { return w[0] === whose; }) ? whose : (stored === 'everyone' ? 'everyone' : 'mine');
  f.owners = csv(p.get('owner')).filter(function (s) { return /^[\w.-]+$/.test(s); });
  return f;
}

export function filtersToSearch(f) {
  const p = new URLSearchParams();
  const statusWords = f.everyStatus ? f.status.concat([EVERY_STATUS]) : f.status;
  if (statusWords.length) p.set('status', statusWords.join(','));
  if (f.project) p.set('project', f.project);
  if (f.person.length) p.set('person', f.person.join(','));
  if (f.due) p.set('due', f.due);
  if (f.updated) p.set('updated', f.updated);
  if (f.q) p.set('q', f.q);
  if (f.sort && f.sort !== 'due') p.set('sort', f.sort);
  if (f.scope && f.scope !== 'mine') p.set('scope', f.scope);
  if (f.owners && f.owners.length) p.set('owner', f.owners.join(','));
  else if (f.whose === 'everyone') p.set('whose', 'everyone');
  const s = p.toString();
  return s ? '?' + s : '';
}

/** Is `t` in `scope`? — the one rule every list that shows the switch reads. */
export function matchesScope(t, scope) {
  if (scope === 'issues') return !!(t && t.issue_ref);
  if (scope === 'all') return true;
  return !(t && t.issue_ref);
}

// ------------------------------------------------------- server params
/** `updated` window → the ISO date the list API's `updated_since` takes. */
export function updatedSince(window, now) {
  if (!window || window.indexOf('stale') === 0) return '';
  const days = window === 'today' ? 0 : (window === 'week' ? 7 : 30);
  return addDays(now || todayISO(), -days);
}

/** `stale*` window → the ISO boundary `updated_before` takes: untouched > N
 * days = last touched strictly before today − N (a task touched exactly N
 * days ago is not YET stale).
 * @param {string} [now]  an ISO *date* (``YYYY-MM-DD``, not a datetime; tests) */
export function updatedBefore(window, now) {
  if (!window || window.indexOf('stale') !== 0) return '';
  return addDays(now || todayISO(), -Number(window.slice(5)));
}

export {
  bumpRecentOwner, MAX_OWNER_SEGMENTS, ownerOf, pickedOwners, pickOwner, RECENT_OWNERS_KEY,
  showsAssignees, storedRecentOwners, toggleOwner, visibleOwners,
} from './js/filters/owners.js';

/** The /api/tasks query for a filter state (undefined = not sent; arrays join with commas).
 *  `owner` is `ownerOf`'s answer — the whose switch's narrowing, sent to the server. */
export function listParams(f, owner) {
  return {
    owner: owner || undefined,
    // a typed query at the resting scope reads the to-do tasks only
    status: queryIsTodoOnly(f) ? f.status.concat(TODO_ONLY) : (f.status.length ? f.status : undefined),
    include_closed: queryCoversEveryStatus(f) || undefined,
    project: f.project || undefined,
    person: f.person.length ? f.person : undefined,
    due: f.due || undefined,
    q: f.q || undefined,
    updated_since: updatedSince(f.updated) || undefined,
    updated_before: updatedBefore(f.updated) || undefined,
  };
}

// -------------------------------------------------- client-side predicate
/** The real statuses among the ticks (not `deferred` / `blocked`). */
function realStatuses(ticks) {
  return ticks.filter(function (s) { return s !== DEFERRED && s !== BLOCKED; });
}

const OPEN_STATUSES = STATUSES.filter(function (s) { return !CLOSED[s]; });
/** Where the status filter rests on Today and Board: a typed search covers the
 *  to-do tasks only, so finished work never crowds it until the pill is removed. */
export const TODO_ONLY = ['todo'];

/** The status ticks a status row and the strip's pills show: the *defaults*
 *  (Search: the open statuses; Today and Board: to do) while the filter is
 *  untouched, nothing once every status is asked for, else the picks. */
export function searchStatusTicks(f, defaults) {
  const modifiers = f.status.filter(function (s) { return s === DEFERRED || s === BLOCKED; });
  if (f.everyStatus) return modifiers;
  const real = realStatuses(f.status);
  return modifiers.concat(real.length ? real : (defaults || OPEN_STATUSES));
}

/** The filter-state patch for the ticks now shown: the defaults ticked is the
 *  resting state (nothing stored), none ticked is every status. */
export function searchStatusPatch(ticks, defaults) {
  const rest = defaults || OPEN_STATUSES;
  const modifiers = ticks.filter(function (s) { return s === DEFERRED || s === BLOCKED; });
  const real = realStatuses(ticks);
  if (!real.length) return { status: modifiers, everyStatus: true };
  const isRest = real.length === rest.length && rest.every(function (s) { return real.indexOf(s) >= 0; });
  return { status: isRest ? modifiers : ticks, everyStatus: false };
}

/** Is a typed query searching every status on Today or Board? — only once the
 *  status pills were all removed (`everyStatus`). Without text the empty ticks
 *  mean the open tasks, so the working lists stay free of finished work. (Search
 *  keeps its text in its own box, never in `f.q`.) */
export function queryCoversEveryStatus(f) {
  return !!(f.q && f.q.trim()) && f.everyStatus && !realStatuses(f.status).length;
}

/** Is a typed query on Today or Board still at the resting scope — to-do tasks
 *  only, the pill nobody has touched? */
export function queryIsTodoOnly(f) {
  return !!(f.q && f.q.trim()) && !f.everyStatus && !realStatuses(f.status).length;
}

/** Do Today and Board list closed tasks? — a status is picked (a closed one
 *  shows only when ticked) or a typed query covers every status. */
export function showsClosed(f) {
  return f.status.length > 0 || queryCoversEveryStatus(f);
}

/** Which statuses a search covers, in words — the count line and the
 *  "no matches" line carry it, so an empty result never leaves it open whether
 *  done and cancelled tasks were looked at. `resting` is what an untouched
 *  filter covers on the tab asking (Search: open only; Today and Board: to do). */
export function statusCoverage(f, resting) {
  const real = realStatuses(f.status);
  if (real.length) return real.length === STATUSES.length ? 'every status' : real.join(', ');
  return f.everyStatus ? 'every status' : (resting || 'open only');
}

/**
 * The same filter applied in the browser — for rows that did not come through
 * /api/tasks (the Search tab's hits). Text (`q`) is not applied here: the
 * search box owns the text on that tab.
 * @param {object} t  a task summary (status, root, breadcrumb, person_id, due, updated_at)
 * @param {object} f  the filter state
 * @param {string} [today]  ISO date (tests)
 */
export function matchesFilters(t, f, today) {
  // Deferral is a modifier, not a status, so it is resolved before the status
  // branch and intersects with whatever real statuses are ticked. Note the
  // asymmetry with the server's default: ticking `deferred` narrows to
  // the sleeping tasks here too, but NOT ticking it hides nothing — the only
  // caller is the Search tab, and a deferred task is meant to stay findable.
  if (f.status.indexOf(DEFERRED) >= 0 && !isDeferred(t, today)) return false;
  // Same shape as deferred: ticking `blocked` narrows to tasks with an
  // open blocker; not ticking it hides nothing (a blocked task stays findable
  // wherever this predicate runs — the Search tab).
  if (f.status.indexOf(BLOCKED) >= 0 && !isBlocked(t)) return false;
  const statuses = realStatuses(f.status);
  if (statuses.length) { if (statuses.indexOf(t.status) < 0) return false; }
  else if (!f.everyStatus && CLOSED[t.status]) return false;
  if (f.project) {
    const pid = String(f.project);
    const inCrumb = (t.breadcrumb || []).some(function (c) { return String(c.id) === pid; });
    if (!inCrumb && !(t.root && String(t.root.id) === pid)) return false;
  }
  if (f.person.length) {
    const who = t.person_id != null ? t.person_id : (t.person ? t.person.id : null);
    if (f.person.indexOf(String(who)) < 0) return false;
  }
  if (f.due) {
    const tIso = today || todayISO();
    if (!t.due) return false;
    if (f.due === 'today' && t.due !== tIso) return false;
    if (f.due === 'overdue' && !(t.due < tIso)) return false;
    if (f.due === 'week') {
      if (t.due < tIso || t.due > addDays(tIso, 7)) return false;
    }
  }
  if (f.updated) {
    const day = t.updated_at ? String(t.updated_at).slice(0, 10) : '';
    const before = updatedBefore(f.updated, today);
    if (before) { if (!day || day >= before) return false; }
    else if (!day || day < updatedSince(f.updated, today)) return false;
  }
  return true;
}

// ------------------------------------------------------------ summary
/** What is active, in words — the filter button's accessible name and title,
 * so the line the old card's summary carried is still one hover or one
 * screen-reader stop away. The text is not in it: it is in the field
 * beside the button. A hidden control's value is not applied, so not described. */
export function describeFilters(f, options) {
  const o = options || {};
  const hidden = new Set(o.hide || []);
  const bits = [];
  if (f.status.length && !hidden.has('status')) bits.push(f.status.join(', '));
  if (o.searchStatus && f.everyStatus && !hidden.has('status')) bits.push('every status');
  if (f.project && !hidden.has('project')) {
    const p = (o.projects || []).find(function (x) { return String(x.id) === String(f.project); });
    bits.push(p ? p.title : 'project #' + f.project);
  }
  if (f.person.length && !hidden.has('person')) {
    bits.push(f.person.map(function (id) {
      const p = (o.people || []).find(function (x) { return String(x.id) === String(id); });
      return p ? p.name : 'person #' + id;
    }).join(', '));
  }
  if (f.due && !hidden.has('due')) bits.push((DUE_WINDOWS.find(function (w) { return w[0] === f.due; }) || [])[1].toLowerCase());
  if (f.updated && !hidden.has('updated')) bits.push((UPDATED_WINDOWS.find(function (w) { return w[0] === f.updated; }) || [])[1].toLowerCase());
  if (f.sort && f.sort !== 'due' && !hidden.has('sort')) bits.push('sorted by ' + sortLabel(f.sort));
  return bits;
}

/** How many of the sheet's filter and sort settings Clear would reset. Not the
 *  text (the field beside the button shows it) and not the view toggles
 *  (`activeViewCount`); a non-default sort does count, since Clear resets it
 *  too. A hidden control's value is not applied, so not counted. */
export function activeFilterCount(f, hide, searchStatus) {
  const hidden = new Set(hide || []);
  let n = 0;
  if ((f.status.length || (searchStatus && f.everyStatus)) && !hidden.has('status')) n += 1;
  if (f.project && !hidden.has('project')) n += 1;
  if (f.person.length && !hidden.has('person')) n += 1;
  if (f.due && !hidden.has('due')) n += 1;
  if (f.updated && !hidden.has('updated')) n += 1;
  if (f.sort && f.sort !== 'due' && !hidden.has('sort')) n += 1;
  return n;
}

/**
 * How many of the view toggles a Today or Board sheet carries are off their
 * default: the kind of task (anything but Tasks) and whose tasks (Everyone or
 * picked people, only where two or more members exist and the row is drawn).
 * Added to `activeFilterCount` for the badge on those tabs.
 * @param {object} f  the filter state
 * @param {number} members  how many members the install has
 */
export function activeViewCount(f, members) {
  let n = 0;
  if (f.scope && f.scope !== 'mine') n += 1;
  if (members >= 2 && ((f.owners && f.owners.length) || f.whose === 'everyone')) n += 1;
  return n;
}

/** The view toggles that are on, in words, for the filter button's name.
 *  @param {Array<{id: string, name: string}>} members */
export function describeViews(f, members) {
  const bits = [];
  if (f.scope && f.scope !== 'mine') {
    bits.push((SCOPES.find(function (s) { return s[0] === f.scope; }) || [])[1].toLowerCase());
  }
  if (members.length >= 2) {
    if (f.owners && f.owners.length) {
      bits.push(f.owners.map(function (id) {
        const m = members.find(function (x) { return x.id === id; });
        return m ? m.name : id;
      }).join(', '));
    } else if (f.whose === 'everyone') bits.push('everyone');
  }
  return bits;
}

/** Do two states draw the same sheet? (the text, the scope and whose are not on it) */
function sameControls(a, b) {
  const strip = { q: '', scope: 'mine', whose: 'mine', owners: [] };
  return filtersToSearch(Object.assign({}, a, strip)) === filtersToSearch(Object.assign({}, b, strip));
}

// One word each, so five segments share a phone-width sheet without wrapping;
// the longer SORTS names stay for the sentence in the strip's filter summary.
const SORT_SEGMENT_LABELS = { due: 'Due', priority: 'Priority', updated: 'Modified', created: 'Created', title: 'Title' };

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ---------------------------------------------------------------- controls
function selectEl(name, label, values, current, onChange) {
  const sel = document.createElement('select');
  sel.dataset.track = 'filters.select';
  sel.className = 'select-native filter-select';
  sel.name = name;
  sel.setAttribute('aria-label', label);
  values.forEach(function (v) {
    const o = document.createElement('option');
    o.value = String(v[0]);
    o.textContent = v[1];
    if (String(v[0]) === String(current)) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () { onChange(sel.value); });
  return sel;
}

/**
 * One choice among a few peers as the vendored segmented control: the raised
 * segment is the state, flipped here once the change is handed on.
 * @param {string} name
 * @param {string} label   the group's accessible name
 * @param {Array<[string,string]>} values   [value, label], two to five
 * @param {string} current
 * @param {(next: string) => void} onChange
 */
function segmentedEl(name, label, values, current, onChange) {
  const group = document.createElement('div');
  group.className = 'segmented filter-segmented';
  group.dataset.name = name;
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  values.forEach(function (v) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset.value = String(v[0]);
    b.dataset.track = 'filters.segment';
    b.setAttribute('aria-pressed', String(String(v[0]) === String(current)));
    b.textContent = v[1];
    group.appendChild(b);
  });
  group.addEventListener('click', function (ev) {
    const seg = ev.target.closest('.segmented-item');
    if (!seg || seg.getAttribute('aria-pressed') === 'true') return;
    group.querySelectorAll('.segmented-item').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b === seg));
    });
    onChange(seg.dataset.value);
  });
  return group;
}

/**
 * Several-allowed choices as ticks in place: the sheet has the room the
 * old card's popover checklist lacked, so status and person are a group of
 * checkboxes, one tap each.
 * @param {string} name
 * @param {string} labelId   the id of the row label that names the group
 * @param {Array<[string,string]>} values   [value, label]
 * @param {Array<string>} selected
 * @param {(next: Array<string>) => void} onChange
 */
function checkGroup(name, labelId, values, selected, onChange) {
  const group = document.createElement('div');
  group.className = 'filter-checks';
  group.dataset.name = name;
  group.setAttribute('role', 'group');
  group.setAttribute('aria-labelledby', labelId);
  values.forEach(function (v) {
    const opt = document.createElement('label');
    opt.className = 'filter-check';
    opt.dataset.value = String(v[0]);
    const cb = document.createElement('input');
    cb.dataset.track = 'filters.option';
    cb.type = 'checkbox';
    cb.className = 'check';
    cb.name = name;
    cb.value = String(v[0]);
    cb.checked = selected.indexOf(String(v[0])) >= 0;
    cb.addEventListener('change', function () {
      const ticked = [];
      group.querySelectorAll('input:checked').forEach(function (el) { ticked.push(el.value); });
      onChange(ticked);
    });
    opt.append(cb, document.createTextNode(v[1]));
    group.appendChild(opt);
  });
  return group;
}

/** One labelled row of the sheet; `viewrows.js` builds its toggle rows with it. */
export function sheetRow(name, label, control) {
  const r = document.createElement('div');
  r.className = 'row filter-sheet-row';
  r.dataset.name = name;
  const l = document.createElement('span');
  l.id = 'filterSheet-' + name;
  l.textContent = label;
  r.append(l, control);
  return r;
}

/** The sheet's controls in their order, each change through `set(name)` (the
 *  tick-model status row passes `true` after the value: it commits through `searchStatusPatch`);
 *  a name in `hidden` is left out. `afterSort` draws the tab's view toggles
 *  between the sort and the filters. `statusDefaults` is the tick model's resting
 *  set (null: the plain ticks of the journal). */
function sheetControls(body, f, options, hidden, set, afterSort, statusDefaults) {
  // 1. sort first: it orders every list, filtered or not
  if (!hidden.has('sort')) {
    const r = sheetRow('sort', 'Sort', segmentedEl('sort', 'Sort', SORTS.map(function (s) { return [s[0], SORT_SEGMENT_LABELS[s[0]] || cap(s[1])]; }), f.sort, set('sort')));
    r.classList.add('is-stacked');
    body.appendChild(r);
  }
  afterSort(body);
  // 2. status — `deferred` and `blocked` ride the end: the one visible way
  //    to see the sleeping and the locked tasks the working views
  //    leave out. None ticked = the open tasks (on Search, every status).
  if (!hidden.has('status')) {
    const statusValues = STATUSES.concat([DEFERRED, BLOCKED]).map(function (s) { return [s, cap(s)]; });
    // Search and the working views draw their resting statuses ticked and take "none ticked" as every status
    const r = sheetRow('status', 'Status', statusDefaults
      ? checkGroup('status', 'filterSheet-status', statusValues, searchStatusTicks(f, statusDefaults), function (ticks) { set('status')(ticks, true); })
      : checkGroup('status', 'filterSheet-status', statusValues, f.status, set('status')));
    r.classList.add('is-stacked');
    body.appendChild(r);
  }
  // 3. project · person
  if (!hidden.has('project')) {
    const projectValues = [['', 'All projects']].concat((options.projects || []).map(function (p) {
      return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
    }));
    body.appendChild(sheetRow('project', 'Project', selectEl('project', 'Project', projectValues, f.project, set('project'))));
  }
  const people = options.people || [];
  if (!hidden.has('person') && (people.length || f.person.length)) {
    const r = sheetRow('person', 'Person', checkGroup('person', 'filterSheet-person',
      people.map(function (p) { return [String(p.id), p.name]; }), f.person, set('person')));
    r.classList.add('is-stacked');
    body.appendChild(r);
  }
  // 4. due · modified
  if (!hidden.has('due')) body.appendChild(sheetRow('due', 'Due', selectEl('due', 'Due window', DUE_WINDOWS, f.due, set('due'))));
  if (!hidden.has('updated')) body.appendChild(sheetRow('updated', 'Modified', selectEl('updated', 'Modified window', UPDATED_WINDOWS, f.updated, set('updated'))));
}

/** The sheet's footer → `{actions, clear}`: Clear (hidden while nothing is
 *  set) and Done.
 *
 *  Applied as they change, so the footer's one primary only closes; Clear
 *  sits beside it while there is something to clear. Not the modal's
 *  sticky `detail-actions` bar: on a phone the sheet scrolls, and a bar
 *  pinned over the last rows overlapped their selects' tap areas (TOUCH-02
 *  on the live walk) — closing never needs to be pinned, the × is. */
function sheetActions(clearHidden, onClear, onDone) {
  const actions = document.createElement('div');
  actions.className = 'filter-actions';
  const clear = document.createElement('button');
  clear.dataset.track = 'filters.clear';
  clear.type = 'button';
  clear.className = 'button-ghost filter-clear';
  clear.textContent = 'Clear';
  clear.hidden = clearHidden;
  clear.addEventListener('click', onClear);
  actions.appendChild(clear);
  const done = document.createElement('button');
  done.dataset.track = 'filters.done';
  done.type = 'button';
  done.className = 'button-primary filter-done';
  done.textContent = 'Done';
  done.addEventListener('click', onDone);
  actions.appendChild(done);
  return { actions: actions, clear: clear };
}

/** The strip's filter button: the glyph and its (empty) count badge. */
function filterButton() {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'icon-button filter-open';
  button.dataset.track = 'filter';
  button.setAttribute('aria-haspopup', 'dialog');
  button.innerHTML = icon('list-filter');
  const badge = document.createElement('span');
  badge.className = 'filter-count';
  button.appendChild(badge);
  return button;
}

/** The strip's one-tap clear: a × beside the filter button, there only while
 *  something is on, like the search box's. */
function clearAllButton() {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'icon-button filter-clear-all';
  button.dataset.track = 'filters.clear-all';
  button.setAttribute('aria-label', 'Clear filters');
  button.title = 'Clear filters';
  button.hidden = true;
  button.innerHTML = icon('x');
  return button;
}

/** The badge's number, and a name that spells out what is on; the × shows with it. */
function paintFilterButton(button, badge, filters, options, opts, clearAll) {
  const views = opts.views;
  const n = activeFilterCount(filters, opts.hide, opts.searchStatus) + (views ? views.count(filters) : 0);
  badge.textContent = n ? String(n) : '';
  badge.hidden = !n;
  clearAll.hidden = !n;
  button.classList.toggle('has-value', n > 0);
  const words = describeFilters(filters, { projects: options.projects, people: options.people, hide: opts.hide, searchStatus: opts.searchStatus })
    .concat(views ? views.words(filters) : []);
  const name = n ? 'Filter, ' + n + ' on: ' + words.join(' · ') : 'Filter';
  button.setAttribute('aria-label', name);
  button.title = name;
}

/** One removable status pill: the fleet chip with its × inside, on a button the
 *  field's full height so the target is real geometry and the chip only its look. */
function statusPill(status, onRemove) {
  const label = cap(status);
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'filter-pill';
  b.dataset.status = status;
  b.dataset.track = 'filter.pill';
  b.setAttribute('aria-label', 'Remove ' + label + ' filter');
  b.title = 'Remove ' + label + ' filter';
  const chip = document.createElement('span');
  chip.className = 'chip';
  const name = document.createElement('span');
  name.className = 'chip-label';
  name.textContent = label;
  chip.appendChild(name);
  chip.insertAdjacentHTML('beforeend', icon('x'));
  b.appendChild(chip);
  b.addEventListener('click', function () { onRemove(status); });
  return b;
}

/** The strip's text field: `onValue(trimmed)` once typing pauses. */
function textInput(onValue) {
  const el = document.createElement('input');
  el.type = 'search';
  el.className = 'input-native filter-q';
  el.setAttribute('aria-label', 'Filter text');
  let timer = 0;
  el.addEventListener('input', function () {
    window.clearTimeout(timer);
    const value = el.value.trim();
    timer = window.setTimeout(function () { onValue(value); }, TEXT_DEBOUNCE_MS);
  });
  return el;
}

/** What Clear leaves: the defaults, keeping — where this tab has no text field
 *  of its own (Search) — the query, and — where the scope, whose and the picked
 *  people are not rows of its sheet (every tab but Today and Board) — those. */
function clearedFilters(base, keepQuery, keepViews) {
  const kept = { q: keepQuery ? base.q : '' };
  if (keepViews) Object.assign(kept, { scope: base.scope, whose: base.whose, owners: base.owners });
  return Object.assign({}, DEFAULT_FILTERS, kept);
}

/** The count's one home is the text field's placeholder. */
function textPlaceholder(count, countLabel) {
  return count == null ? 'Filter text…'
    : 'Filter ' + count + ' ' + (countLabel ? countLabel + ' ' : '') + (count === 1 ? 'task' : 'tasks') + '…';
}

/** The sheet's editor-modal card; its × closes the dialog. */
function filterCard(dialog) {
  return modalCard({
    cardClass: 'filter-card', title: 'Filters & sort', titleId: 'filterSheetTitle',
    closeLabel: 'Close filters & sort', onClose: function () { dialog.close(); },
  }).card;
}

/** The card's rows region, appended to *card*: its own scroll area, so the
 *  footer below it stays on screen on a phone. */
function sheetBody(card) {
  const body = document.createElement('div');
  body.className = 'filter-body';
  card.appendChild(body);
  return body;
}

function focusClose(dialog) {
  const c = dialog.querySelector('.detail-close');
  if (c) c.focus();
}

/** Does the sheet hold anything Clear would reset — a filter or a view toggle?
 *  The view toggles are read from the live state: `drawn` only holds what the sheet last drew. */
function sheetHasValue(f, opts) {
  const live = opts.views ? Object.assign({}, f, opts.views.live()) : f;
  return !!(activeFilterCount(live, opts.hide, opts.searchStatus) + (opts.views ? opts.views.count(live) : 0));
}

/**
 * The pane strip's two controls, built once and updated in place: the live text
 * field (when the tab has a `textHost`) and the filter button beside it.
 * @param {object} opts  `mountFilters`' options
 * @param {() => {current: object, options: object}} read  the state last rendered and its options
 * @param {() => void} onOpen  opens the sheet
 * @param {string[]|null} statusDefaults  the resting statuses of the tick model, null on the journal
 * @param {() => void} onClear  resets every filter, the sheet's Clear and the strip's × alike
 */
function mountStrip(opts, read, onOpen, statusDefaults, onClear) {
  let textEl = null;
  let pillsEl = null;
  let pillsKey = null;
  let button = null;
  let badge = null;
  let clearAll = null;

  /** The status filter as pills inside the field: the same ticks the sheet draws,
   *  so removing one is un-ticking it there — one state, never two. */
  function renderPills(filters) {
    const ticks = searchStatusTicks(filters, statusDefaults);
    const key = ticks.join(',');
    if (key === pillsKey) return;
    pillsKey = key;
    pillsEl.hidden = !ticks.length;
    pillsEl.replaceChildren.apply(pillsEl, ticks.map(function (status) {
      return statusPill(status, function (gone) {
        const left = searchStatusTicks(read().current, statusDefaults).filter(function (t) { return t !== gone; });
        opts.onChange(Object.assign({}, read().current, searchStatusPatch(left, statusDefaults)));
      });
    }));
  }

  function renderText(filters, options) {
    if (!opts.textHost) return;
    if (!textEl) {
      textEl = textInput(function (value) { opts.onChange(Object.assign({}, read().current, { q: value })); });
      if (statusDefaults) {
        const field = document.createElement('div');
        field.className = 'filter-field';
        pillsEl = document.createElement('div');
        pillsEl.className = 'filter-pills';
        pillsEl.setAttribute('role', 'group');
        pillsEl.setAttribute('aria-label', 'Status filter');
        field.append(pillsEl, textEl);
        opts.textHost.replaceChildren(field);
      } else opts.textHost.replaceChildren(textEl);
    }
    if (pillsEl) renderPills(filters);
    opts.textHost.hidden = false;
    // Never yank the value out from under the typist: their keystrokes are
    // already in the box and the debounce means `filters.q` trails them.
    if (document.activeElement !== textEl && textEl.value !== filters.q) textEl.value = filters.q;
    textEl.placeholder = textPlaceholder(options.count, opts.countLabel);
  }

  function renderButton(filters, options) {
    const host = opts.buttonHost || opts.textHost;
    if (!host) return;
    if (!button) {
      button = filterButton();
      badge = button.querySelector('.filter-count');
      button.addEventListener('click', onOpen);
      clearAll = clearAllButton();
      clearAll.addEventListener('click', onClear);
      host.append(button, clearAll);
    }
    paintFilterButton(button, badge, filters, options, opts, clearAll);
  }

  return { render: function (filters) { const o = read().options; renderText(filters, o); renderButton(filters, o); } };
}

// ---------------------------------------------------------------- sheet
const SHEET_ID = 'filterSheet';
let sheetOwner = null;   // the mountFilters handle whose controls the one sheet shows

/**
 * Mount one tab's filter controls; call `render(filters, options)` on every
 * state change. One instance per tab, all reading the same state.
 *
 * The strip: the text field and, beside it, the filter button carrying
 * the active-filter count; the button opens the sheet — the vendored editor
 * modal (`#filterSheet`, static in index.html like the date sheet) with sort
 * first, then status · project · person · due · modified, applied as they
 * change. The tabs share the one `<dialog>`; whichever instance opened it
 * draws its controls.
 * @param {{onChange: (f: object) => void, textHost?: HTMLElement, buttonHost?: HTMLElement,
 *          hide?: string[], countLabel?: string, searchStatus?: boolean}} opts
 *          textHost — where the always-visible text input goes (the pane's top
 *          strip). Omitted on the Search tab: its own box owns the text,
 *          so there is no second text field and Clear leaves the query alone.
 *          buttonHost — where the filter button goes; defaults to `textHost`
 *          (Search passes its own box).
 *          countLabel — the word before "tasks" in the text field's
 *          placeholder, which carries the list's count ("Filter 12 closed
 *          tasks…")
 *          searchStatus — the tick model: the status row draws the resting statuses
 *          ticked, and none ticked means every status (`everyStatus`); a tab with
 *          a text field also shows them as removable pills inside it
 *          statusDefaults — the resting statuses of that model (default: the open
 *          statuses, Search's; Today and Board pass `TODO_ONLY`)
 *          hide — control names this tab leaves out (`status` · `due` ·
 *          `updated` · `sort` · `project` · `person`); the journal
 *          drops the four that say nothing about a closed task. A hidden
 *          control's value is neither drawn, counted nor described.
 *          views — the view toggles this tab's sheet carries above sort
 *          (Today and Board; js/app/viewrows.js): `count(f)` and `words(f)`
 *          feed the button's badge and name, `draw(body)` builds the rows,
 *          `sync(f)` brings an open sheet's rows up to date, `live()` is the
 *          scope · whose · owners the app holds right now (a sheet change
 *          never writes back a stale copy of them) and `clear()` resets what
 *          the filter state does not hold (the Board's layout).
 * @returns {{render: (filters: object, options: {projects: Array, people: Array, count?: number}) => void,
 *            openSheet: () => void}}
 */
export function mountFilters(opts) {
  const hidden = new Set(opts.hide || []);
  // the tick model (Search and the working views): the resting statuses the row ticks
  // and the pills show; null on the journal, whose status is implicit
  const statusDefaults = opts.searchStatus ? (opts.statusDefaults || OPEN_STATUSES) : null;
  const strip = mountStrip(opts, function () { return { current: current, options: options }; }, function () { openSheet(); }, opts.textHost ? statusDefaults : null, function () { clearAll(); });
  let current = DEFAULT_FILTERS;   // the state last rendered
  let options = {};
  let drawn = null;          // the state the open sheet's controls show; null while closed
  let sheetClear = null;     // the open sheet's Clear button
  const handle = { render: render, openSheet: openSheet };

  function render(filters, o) {
    current = filters;
    options = o || {};
    strip.render(filters);
    // A change from outside the sheet (the palette's filter commands) redraws
    // an open sheet; one the sheet itself made already shows, so it is left
    // alone and the control the user is on keeps the focus.
    const dialog = document.getElementById(SHEET_ID);
    if (sheetOwner === handle && dialog && dialog.open && drawn && !sameControls(filters, drawn)) {
      const hadFocus = dialog.contains(document.activeElement);
      drawn = filters;
      drawSheet(dialog);
      if (hadFocus) focusClose(dialog);
    } else if (sheetOwner === handle && opts.views && dialog && dialog.open) {
      // the view toggles are redrawn in place: the control just pressed keeps the focus
      opts.views.sync(filters);
      if (sheetClear) sheetClear.hidden = !sheetHasValue(drawn || filters, opts);
    }
  }

  /** Commit one sheet change: built on what the sheet shows, so two quick
   *  changes never lose the first to a render still on its way. The controls
   *  already show it; only Clear follows. */
  function commit(patch) {
    drawn = Object.assign({}, drawn || current, patch, opts.views ? opts.views.live() : {});
    if (sheetClear) sheetClear.hidden = !sheetHasValue(drawn, opts);
    opts.onChange(drawn);
  }

  /** Reset every filter (and the view toggles) — the one rule behind the sheet's
   *  Clear and the strip's ×. With the sheet shut `drawn` is null and stays so:
   *  a stale copy there would be read as what the next sheet change builds on. */
  function clearAll() {
    if (opts.views) opts.views.clear();
    const cleared = clearedFilters(drawn || current, !opts.textHost, !opts.views);
    if (drawn) drawn = cleared;
    opts.onChange(cleared);
  }

  function drawSheet(dialog) {
    const f = drawn || current;
    drawn = f;
    const card = filterCard(dialog);
    const body = sheetBody(card);
    sheetControls(body, f, options, hidden, function (name) {
      return function (value, searchTicks) { const p = {}; p[name] = value; commit(searchTicks ? searchStatusPatch(value, statusDefaults) : p); };
    }, function (rows) { if (opts.views) opts.views.draw(rows, f); }, statusDefaults);
    const foot = sheetActions(!sheetHasValue(f, opts), function () {
      clearAll();
      drawSheet(dialog);
      focusClose(dialog);
    }, function () { dialog.close(); });
    sheetClear = foot.clear;
    card.appendChild(foot.actions);
    dialog.replaceChildren(card);
  }

  function openSheet() {
    const dialog = document.getElementById(SHEET_ID);
    if (!dialog) return;
    if (dialog.open) dialog.close();
    sheetOwner = handle;
    drawn = null;
    onceClosed(dialog, function () {
      drawn = null;
      sheetClear = null;
      if (sheetOwner === handle) sheetOwner = null;
    });
    drawSheet(dialog);
    dialog.showModal();
  }

  return handle;
}
