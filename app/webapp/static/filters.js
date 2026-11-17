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
 *   <dialog id="filterSheet">         what the button opens — the vendored
 *                                     editor modal: sort first, then status ·
 *                                     project · person · due · modified;
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

export const DEFAULT_FILTERS = { status: [], project: '', person: [], due: '', updated: '', q: '', sort: 'due', scope: 'mine', whose: 'mine', owners: [] };
/**
 * Which kind of task a list shows: the ones you
 * make, the issues the forge sync brings in, or both — labelled Tasks · Issues
 * · All, when "Mine" became the other axis (`WHOSE`). A task is an
 * issue when it carries an `issue_ref` — the coding task the sync made
 * (`coding` ⇔ issue_ref). One URL key, `scope`, absent for the default (its
 * id stays `mine`, so every saved `?scope=` link keeps working). It is not a
 * sheet control: the segmented switch under the strip owns it (scope.js), so
 * the sheet neither counts it nor resets it on Clear.
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
 * Like the scope the row is a switch's, never the sheet's, so Clear leaves
 * both alone. The Search tab ignores them: search covers everyone.
 */
export const WHOSE = [['mine', 'Mine'], ['everyone', 'Everyone']];
/** The person row is one segmented control, which holds at most this many
 *  segments (Mine, the people, "+N more", Everyone); more members go behind "+N more". */
export const MAX_OWNER_SEGMENTS = 5;
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
  f.status = csv(p.get('status')).filter(function (s) { return STATUSES.indexOf(s) >= 0 || s === DEFERRED || s === BLOCKED; });
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
  if (f.status.length) p.set('status', f.status.join(','));
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

/**
 * The member id(s) a view narrows to, comma-joined, or undefined when nothing
 * narrows: the install has fewer than two members (no row, nothing to narrow),
 * or it is on Everyone, or Mine with the viewer not known — an unknown never
 * hides a task. Picked people win over Mine · Everyone. The server counts a
 * NULL owner as the install owner's.
 * @param {object} f  the filter state
 * @param {string|null} viewer  `GET /api/me`'s id
 * @param {number} members  how many members the install has
 */
export function ownerOf(f, viewer, members) {
  if (members < 2) return undefined;
  if (f.owners && f.owners.length) return f.owners.join(',');
  return f.whose === 'mine' && viewer ? String(viewer) : undefined;
}

/** The members the person row has pressed: the picked ones, else the viewer
 *  under Mine, else nobody (Everyone, or a viewer that is not known). */
export function pickedOwners(f, viewer) {
  if (f.owners && f.owners.length) return f.owners;
  return f.whose === 'mine' && viewer ? [String(viewer)] : [];
}

/** Does a view name each row's assignee? — more than one person is on it. */
export function showsAssignees(f, members) {
  if (members < 2) return false;
  if (f.owners && f.owners.length) return f.owners.length > 1;
  return f.whose === 'everyone';
}

/**
 * The state after a tap on a person segment: that person alone, replacing
 * whatever was picked. The viewer's own segment is Mine, which writes no key.
 * @returns {{owners: string[], whose: string}}
 */
export function pickOwner(id, viewer) {
  if (!id || id === viewer) return { owners: [], whose: 'mine' };
  return { owners: [id], whose: 'mine' };
}

/**
 * The state after a tick in the "+N more" sheet (the one place several people
 * can be picked): the pick toggles in the set the row shows, and a set that
 * empties falls back to Mine, so the row never shows nothing. The viewer alone
 * is Mine, no key.
 * @returns {{owners: string[], whose: string}}
 */
export function toggleOwner(f, id, viewer) {
  if (!id) return { owners: [], whose: 'mine' };
  const at = pickedOwners(f, viewer);
  const next = at.indexOf(id) >= 0 ? at.filter(function (x) { return x !== id; }) : at.concat([id]);
  if (!next.length || (next.length === 1 && next[0] === viewer)) return { owners: [], whose: 'mine' };
  return { owners: next, whose: 'mine' };
}

/**
 * Which people the row draws and how many wait behind "+N more". The row is
 * one segmented control of at most `MAX_OWNER_SEGMENTS` segments: Mine (the
 * viewer), Everyone and the people between. Every non-viewer member shows when
 * they all fit; otherwise one segment goes to "+N more" and the rest keep the
 * picked people, then the recently picked, then the members in their order.
 * `ordered` lists every non-viewer member the same way for the searchable sheet.
 * @param {Array<{id: string, name: string}>} members
 * @param {string|null} viewer
 * @param {string[]} picked  the pressed ids
 * @param {string[]} recent  member ids, most recently picked first
 * @returns {{shown: Array, more: number, ordered: Array}}
 */
export function visibleOwners(members, viewer, picked, recent) {
  const others = members.filter(function (m) { return m.id !== viewer; });
  const rank = function (m) {
    const r = (recent || []).indexOf(m.id);
    return [picked.indexOf(m.id) >= 0 ? 0 : 1, r >= 0 ? r : 1e6, members.indexOf(m)];
  };
  const ordered = others.slice().sort(function (a, b) {
    const x = rank(a), y = rank(b);
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
  });
  // Everyone takes a segment, and so does Mine when the viewer is known.
  const room = MAX_OWNER_SEGMENTS - (viewer ? 2 : 1);
  if (others.length <= room) return { shown: others, more: 0, ordered: ordered };
  return { shown: ordered.slice(0, room - 1), more: ordered.length - (room - 1), ordered: ordered };
}

/** The device's remembered picks, newest first. */
export const RECENT_OWNERS_KEY = 'task-os.recent-owners';
const MAX_RECENT_OWNERS = 8;

/** The remembered ids; an empty, odd or unreadable store reads as none. */
export function storedRecentOwners(storage) {
  try {
    const v = JSON.parse(storage && storage.getItem(RECENT_OWNERS_KEY));
    return Array.isArray(v) ? v.filter(function (x) { return typeof x === 'string'; }).slice(0, MAX_RECENT_OWNERS) : [];
  } catch (_) { return []; }
}

/** `recent` with `id` moved to the front. */
export function bumpRecentOwner(recent, id) {
  return [id].concat((recent || []).filter(function (x) { return x !== id; })).slice(0, MAX_RECENT_OWNERS);
}

/** The /api/tasks query for a filter state (undefined = not sent; arrays join with commas).
 *  `owner` is `ownerOf`'s answer — the whose switch's narrowing, sent to the server. */
export function listParams(f, owner) {
  return {
    owner: owner || undefined,
    status: f.status.length ? f.status : undefined,
    project: f.project || undefined,
    person: f.person.length ? f.person : undefined,
    due: f.due || undefined,
    q: f.q || undefined,
    updated_since: updatedSince(f.updated) || undefined,
    updated_before: updatedBefore(f.updated) || undefined,
  };
}

// -------------------------------------------------- client-side predicate
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
  const statuses = f.status.filter(function (s) { return s !== DEFERRED && s !== BLOCKED; });
  if (statuses.length) { if (statuses.indexOf(t.status) < 0) return false; }
  else if (CLOSED[t.status]) return false;
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

/** How many settings the sheet's Clear would reset — the number on the filter
 *  button. Neither the text (the field beside the button shows it) nor
 *  the scope or whose (the switches') counts; a non-default sort does, since Clear
 *  resets it too. A hidden control's value is not applied, so not counted. */
export function activeFilterCount(f, hide) {
  const hidden = new Set(hide || []);
  let n = 0;
  if (f.status.length && !hidden.has('status')) n += 1;
  if (f.project && !hidden.has('project')) n += 1;
  if (f.person.length && !hidden.has('person')) n += 1;
  if (f.due && !hidden.has('due')) n += 1;
  if (f.updated && !hidden.has('updated')) n += 1;
  if (f.sort && f.sort !== 'due' && !hidden.has('sort')) n += 1;
  return n;
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

function sheetRow(name, label, control) {
  const r = document.createElement('div');
  r.className = 'row filter-sheet-row';
  r.dataset.name = name;
  const l = document.createElement('span');
  l.id = 'filterSheet-' + name;
  l.textContent = label;
  r.append(l, control);
  return r;
}

/** The sheet's controls in their order, each change through `set(name)`;
 *  a name in `hidden` is left out. */
function sheetControls(body, f, options, hidden, set) {
  // 1. sort first: it orders every list, filtered or not
  if (!hidden.has('sort')) {
    const r = sheetRow('sort', 'Sort', segmentedEl('sort', 'Sort', SORTS.map(function (s) { return [s[0], SORT_SEGMENT_LABELS[s[0]] || cap(s[1])]; }), f.sort, set('sort')));
    r.classList.add('is-stacked');
    body.appendChild(r);
  }
  // 2. status — `deferred` and `blocked` ride the end: the one visible way
  //    to see the sleeping and the locked tasks the working views
  //    leave out. None ticked = the open tasks.
  if (!hidden.has('status')) {
    const statusValues = STATUSES.concat([DEFERRED, BLOCKED]).map(function (s) { return [s, cap(s)]; });
    const r = sheetRow('status', 'Status', checkGroup('status', 'filterSheet-status', statusValues, f.status, set('status')));
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

/** The badge's number, and a name that spells out what is on. */
function paintFilterButton(button, badge, filters, options, hide) {
  const n = activeFilterCount(filters, hide);
  badge.textContent = n ? String(n) : '';
  badge.hidden = !n;
  button.classList.toggle('has-value', n > 0);
  const words = describeFilters(filters, { projects: options.projects, people: options.people, hide: hide });
  const name = n ? 'Filter, ' + n + ' on: ' + words.join(' · ') : 'Filter';
  button.setAttribute('aria-label', name);
  button.title = name;
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

/** What Clear leaves: the defaults, keeping the scope, whose, the picked people and — where this
 *  tab has no text field of its own (Search) — the query. */
function clearedFilters(base, keepQuery) {
  return Object.assign({}, DEFAULT_FILTERS, { q: keepQuery ? base.q : '', scope: base.scope, whose: base.whose, owners: base.owners });
}

/** The count's one home is the text field's placeholder. */
function textPlaceholder(count, countLabel) {
  return count == null ? 'Filter text…'
    : 'Filter ' + count + ' ' + (countLabel ? countLabel + ' ' : '') + (count === 1 ? 'task' : 'tasks') + '…';
}

/** The sheet's editor-modal card; its × closes the dialog. */
function filterCard(dialog) {
  return modalCard({
    cardClass: 'filter-card', title: 'Filters', titleId: 'filterSheetTitle',
    closeLabel: 'Close filters', onClose: function () { dialog.close(); },
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
 *          hide?: string[], countLabel?: string}} opts
 *          textHost — where the always-visible text input goes (the pane's top
 *          strip). Omitted on the Search tab: its own box owns the text,
 *          so there is no second text field and Clear leaves the query alone.
 *          buttonHost — where the filter button goes; defaults to `textHost`
 *          (Search passes its own box).
 *          countLabel — the word before "tasks" in the text field's
 *          placeholder, which carries the list's count ("Filter 12 closed
 *          tasks…")
 *          hide — control names this tab leaves out (`status` · `due` ·
 *          `updated` · `sort` · `project` · `person`); the journal
 *          drops the four that say nothing about a closed task. A hidden
 *          control's value is neither drawn, counted nor described.
 * @returns {{render: (filters: object, options: {projects: Array, people: Array, count?: number}) => void,
 *            openSheet: () => void}}
 */
export function mountFilters(opts) {
  const hidden = new Set(opts.hide || []);
  let textEl = null;         // the strip's input — built once, never re-rendered
  let button = null;         // the filter button — built once, updated in place
  let badge = null;
  let current = DEFAULT_FILTERS;   // the state last rendered
  let options = {};
  let drawn = null;          // the state the open sheet's controls show; null while closed
  let sheetClear = null;     // the open sheet's Clear button
  const handle = { render: render, openSheet: openSheet };

  /** The live text filter, in the pane's top strip. */
  function renderText(filters) {
    if (!opts.textHost) return;
    if (!textEl) {
      textEl = textInput(function (value) { opts.onChange(Object.assign({}, current, { q: value })); });
      opts.textHost.replaceChildren(textEl);
    }
    opts.textHost.hidden = false;
    // Never yank the value out from under the typist: their keystrokes are
    // already in the box and the debounce means `filters.q` trails them.
    if (document.activeElement !== textEl && textEl.value !== filters.q) textEl.value = filters.q;
    textEl.placeholder = textPlaceholder(options.count, opts.countLabel);
  }

  /** The filter button: the glyph, plus how many settings are on. */
  function renderButton(filters) {
    const host = opts.buttonHost || opts.textHost;
    if (!host) return;
    if (!button) {
      button = filterButton();
      badge = button.querySelector('.filter-count');
      button.addEventListener('click', openSheet);
      host.appendChild(button);
    }
    paintFilterButton(button, badge, filters, options, opts.hide);
  }

  function render(filters, o) {
    current = filters;
    options = o || {};
    renderText(filters);
    renderButton(filters);
    // A change from outside the sheet (the palette's filter commands) redraws
    // an open sheet; one the sheet itself made already shows, so it is left
    // alone and the control the user is on keeps the focus.
    const dialog = document.getElementById(SHEET_ID);
    if (sheetOwner === handle && dialog && dialog.open && drawn && !sameControls(filters, drawn)) {
      const hadFocus = dialog.contains(document.activeElement);
      drawn = filters;
      drawSheet(dialog);
      if (hadFocus) focusClose(dialog);
    }
  }

  /** Commit one sheet change: built on what the sheet shows, so two quick
   *  changes never lose the first to a render still on its way. The controls
   *  already show it; only Clear follows. */
  function commit(patch) {
    drawn = Object.assign({}, drawn || current, patch);
    if (sheetClear) sheetClear.hidden = !activeFilterCount(drawn, opts.hide);
    opts.onChange(drawn);
  }

  function drawSheet(dialog) {
    const f = drawn || current;
    drawn = f;
    const card = filterCard(dialog);
    sheetControls(sheetBody(card), f, options, hidden, function (name) {
      return function (value) { const p = {}; p[name] = value; commit(p); };
    });
    const foot = sheetActions(!activeFilterCount(f, opts.hide), function () {
      drawn = clearedFilters(drawn || f, !opts.textHost);
      opts.onChange(drawn);
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
