/* task-os — the vendored disclosure card, built in one place.
 *
 * `_vendored/disclosure` ships the CSS and a markup skeleton, no JS, so a card
 * a view creates at runtime has to build that DOM itself: the filter card
 * (filters.js), the Search tab's per-kind groups (search.js) and Today's
 * "Later this week" (today.js). This is that builder — the skeleton's element
 * order and class names exactly, so the vendored rules keep matching. The
 * cards written straight into index.html (Settings) are the static twin.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

/**
 * `<details class="card card--collapsible …">` with the summary row (icon ·
 * title · count · chevron) and an empty body. The caller owns open state,
 * the toggle listener and what goes in the body.
 * @param {{className?: string, icon: string, title: string, count?: string,
 *          countClass?: string, bodyClass?: string}} opts
 * @returns {{card: HTMLDetailsElement, count: HTMLSpanElement, body: HTMLDivElement}}
 */
export function collapsibleCard(opts) {
  const o = opts || {};
  const card = document.createElement('details');
  card.className = 'card card--collapsible' + (o.className ? ' ' + o.className : '');
  const summary = document.createElement('summary');
  summary.className = 'collapse-summary';
  const main = document.createElement('span');
  main.className = 'collapse-main';
  main.innerHTML = icon(o.icon);
  const h = document.createElement('h3');
  h.className = 'collapse-title';
  h.textContent = o.title;
  const count = document.createElement('span');
  count.className = 'collapse-count' + (o.countClass ? ' ' + o.countClass : '');
  count.textContent = o.count || '';
  main.append(h, count);
  const chev = document.createElement('span');
  chev.className = 'collapse-chevron';
  chev.setAttribute('aria-hidden', 'true');
  chev.textContent = '›';
  summary.append(main, chev);
  const body = document.createElement('div');
  body.className = 'collapse-body' + (o.bodyClass ? ' ' + o.bodyClass : '');
  card.append(summary, body);
  return { card: card, count: count, body: body };
}
