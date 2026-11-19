/* task-os — whose tasks a list shows: the pure rules behind the person row
 * (Mine · Everyone · the members) and the device's remembered picks. The filter
 * state that holds `whose` / `owners` is filters.js's, which re-exports these so
 * every caller keeps importing them from there.
 */

'use strict';

/** The person row is one segmented control, which holds at most this many
 *  segments (Mine, the people, "+N more", Everyone); more members go behind "+N more". */
export const MAX_OWNER_SEGMENTS = 5;

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
