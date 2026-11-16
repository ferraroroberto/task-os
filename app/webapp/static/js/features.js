/* task-os — which feature blocks this machine has switched off (src/features.py).
 *
 * The server stamps the page with `<html data-features-off="time email">` and
 * Settings → Available features rewrites it live, so this one attribute is the
 * state every surface reads: CSS hides whatever is tagged `data-feature="<key>"`
 * (styles/base.css) and a module asks `featureOn(key)` before it fetches or polls.
 * Nothing is cached in a variable, so a switch needs no reload. */

'use strict';

const root = document.documentElement;

/** The keys of the blocks that are off. */
export function featuresOff() {
  return (root.dataset.featuresOff || '').split(/\s+/).filter(Boolean);
}

/** True while the block `key` is on — the default for every block. */
export function featureOn(key) {
  return featuresOff().indexOf(key) < 0;
}

/** Replace the off set (after the server confirmed a switch). */
export function setFeaturesOff(keys) {
  if (keys.length) root.dataset.featuresOff = keys.join(' ');
  else delete root.dataset.featuresOff;
}

//: The nav tab each block owns.
const TAB_BLOCK = { time: 'time' };

/** The stored tab to restore: `tab`, unless its block is off — then the stored
 *  choice is dropped, so the nav falls back to its default tab. */
export function restorableTab(tab, storageKey) {
  if (!(tab in TAB_BLOCK) || featureOn(TAB_BLOCK[tab])) return tab;
  try { localStorage.removeItem(storageKey); } catch (_) { /* private mode */ }
  return null;
}
