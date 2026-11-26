/* task-os — Search: the result tiers every search box labels the same way (the
 * Search tab's groups, the folder picker, the command palette). The server
 * sends hits tier by tier with `match_kind`; an exact hit, or one with no
 * tier, carries no label.
 */

'use strict';

/** Best first: the tiers never interleave. */
const TIERS = ['exact', 'partial', 'similar', 'closest'];
const TIER_LABELS = { partial: 'Partial matches', similar: 'Similar matches', closest: 'Closest matches' };

/** @param {string|null|undefined} kind a hit's `match_kind`  @returns {number} 0 for exact */
export function tierOf(kind) { return Math.max(0, TIERS.indexOf(kind)); }

/** The quiet sub-heading above the first row of a weaker tier, as a list item.
 *  @param {number} tier a `tierOf` result above 0 */
export function tierHeading(tier) {
  const li = document.createElement('li');
  li.className = 'search-tier overline';
  li.dataset.tier = TIERS[tier];
  li.setAttribute('role', 'presentation');
  li.textContent = TIER_LABELS[TIERS[tier]];
  return li;
}
