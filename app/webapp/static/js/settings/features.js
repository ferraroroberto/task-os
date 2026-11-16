/* task-os — Settings → Available features: one row per coarse feature block
 * (src/features.py), each with the vendored switch. A switch applies on the
 * spot: the server saves it to this machine's config and starts or stops the
 * block's background work, and the page hides or restores the block's UI with
 * no reload. A block whose dependency is missing here says so on its row.
 *
 * The group is built here because index.html is at its size limit; the rows of
 * the blocks that are off are hidden from the other Settings groups by tagging
 * them `data-feature` (the same attribute that hides the tab). */

'use strict';

import { setSwitch, switchEl } from '../../_vendored/switch/switch.js';
import { api } from '../../api.js';
import { toast } from '../../toast.js';
import { setFeaturesOff } from '../features.js';

//: The Settings rows each block owns, by their `data-settings-sheet` key.
const SHEET_OWNER = {
  issues: 'issues', calendar: 'calendar', capture: 'email', archive: 'email',
  voice: 'ai', ai: 'ai', mirror: 'mirror', timecats: 'time',
};

/** Tag every Settings row whose block can be switched off, so CSS hides it with the block. */
function tagOwnedRows(pane) {
  Object.keys(SHEET_OWNER).forEach(function (sheet) {
    const row = pane.querySelector('[data-settings-sheet="' + sheet + '"]');
    const item = row && row.closest('li');
    if (item) item.dataset.feature = SHEET_OWNER[sheet];
  });
}

function rowEl(f, onToggle) {
  const li = document.createElement('li');
  li.className = 'action-row settings-feature';
  li.dataset.featureKey = f.key;
  const main = document.createElement('div');
  main.className = 'action-row-main settings-feature-main';
  const title = document.createElement('span');
  title.className = 'action-row-title';
  title.textContent = f.label;
  const summary = document.createElement('span');
  summary.className = 'action-row-meta';
  summary.textContent = f.summary;
  const state = document.createElement('span');
  state.className = 'action-row-meta settings-feature-state';
  main.append(title, summary, state);
  const sw = switchEl(f.enabled, { label: f.label, onToggle: onToggle });
  sw.classList.add('action-row-trail');
  // dynamic-id-exempt: the id is the block key, a fixed set of six
  sw.dataset.track = 'settings.feature-' + f.key;
  li.append(main, sw);
  return li;
}

/** The state line under a row: off, or on but unavailable here with the reason. */
function paintState(li, f) {
  const state = li.querySelector('.settings-feature-state');
  if (!f.enabled) {
    state.textContent = 'Off on this machine';
    delete state.dataset.tone;
  } else if (!f.available) {
    state.textContent = 'On, unavailable here: ' + f.reason;
    state.dataset.tone = 'attention';
  } else {
    state.textContent = 'On';
    delete state.dataset.tone;
  }
  setSwitch(li.querySelector('.toggle'), f.enabled);
}

/** Build the group before "This install", tag the owned rows, load the state.
 *  Returns `{refresh}` for the bootstrap to call when Settings opens. */
export function mountFeatures(ctx) {
  const anchor = document.getElementById('settingsGroupInstall');
  const heading = document.createElement('h2');
  heading.className = 'overline settings-overline';
  heading.id = 'settingsGroupFeatures';
  heading.textContent = 'Available features';
  const group = document.createElement('section');
  group.className = 'card action-list settings-group';
  group.setAttribute('aria-labelledby', heading.id);
  const list = document.createElement('ul');
  list.className = 'action-rows';
  const note = document.createElement('p');
  note.className = 'card-meta settings-features-note';
  note.setAttribute('role', 'status');
  group.append(list);
  anchor.before(heading, group, note);
  tagOwnedRows(ctx.els.pane);

  let busy = false;
  let current = [];

  function paint(features) {
    current = features;
    list.replaceChildren();
    features.forEach(function (f) {
      const li = rowEl(f, function (next) { toggle(f, next); });
      list.appendChild(li);
      paintState(li, f);
    });
    setFeaturesOff(features.filter(function (f) { return !f.enabled; }).map(function (f) { return f.key; }));
  }

  async function toggle(f, next) {
    if (busy) return;
    busy = true;
    note.textContent = '';
    try {
      const res = await api('/api/features/' + f.key, { method: 'PUT', body: { enabled: next } });
      paint(res.features);
      // The rows were redrawn: keep the keyboard where it was.
      const again = list.querySelector('[data-feature-key="' + f.key + '"] .toggle');
      if (again) again.focus({ preventScroll: true });
      note.textContent = f.label + (next ? ' is on.' : ' is off: its screens are hidden and its background work has stopped.');
      ctx.opts.onFeatures(f.key, next);
    } catch (err) {
      note.textContent = err.message || 'Could not save the switch';
      toast(err.message || 'Could not save the switch', 'error');
    }
    busy = false;
  }

  async function refresh() {
    try {
      paint((await api('/api/features')).features);
    } catch (err) {
      list.replaceChildren();
      note.textContent = 'Features unknown — ' + (err.message || 'unreachable');
    }
  }

  refresh();
  return { refresh: refresh, current: function () { return current; } };
}
