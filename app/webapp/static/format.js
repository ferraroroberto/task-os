/* task-os — formatting helpers shared by the Table, Tree and drawer.
 *
 * Relative dates, timestamps, link chips (URLs / folder placeholders /
 * repo#N inside comment bodies) and a deliberately small markdown renderer
 * for descriptions. Everything escapes text before it touches innerHTML.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

export const STATUSES = ['inbox', 'todo', 'doing', 'standby', 'done', 'cancelled'];
export const PRIORITIES = ['high', 'medium', 'low', 'none'];
export const RECURRENCES = ['', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'];

const DAY_MS = 86400000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Local calendar date as YYYY-MM-DD (never toISOString — that is UTC). */
export function todayISO(d) {
  const t = d || new Date();
  const m = String(t.getMonth() + 1).padStart(2, '0');
  const day = String(t.getDate()).padStart(2, '0');
  return t.getFullYear() + '-' + m + '-' + day;
}

function parseISO(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/**
 * Relative due label + tone. `{text, tone}` where tone ∈ '' | 'today' |
 * 'overdue' — the Table tints overdue with the danger token.
 */
export function relDue(iso, now) {
  const d = parseISO(iso);
  if (!d) return { text: '', tone: '' };
  const t = parseISO(todayISO(now));
  const diff = Math.round((d - t) / DAY_MS);
  if (diff === 0) return { text: 'today', tone: 'today' };
  if (diff === 1) return { text: 'tomorrow', tone: '' };
  if (diff === -1) return { text: 'yesterday', tone: 'overdue' };
  if (diff < 0) {
    const n = -diff;
    return { text: (n < 14 ? n + 'd' : Math.round(n / 7) + 'w') + ' ago', tone: 'overdue' };
  }
  if (diff < 14) return { text: 'in ' + diff + 'd', tone: '' };
  if (diff < 60) return { text: 'in ' + Math.round(diff / 7) + 'w', tone: '' };
  return { text: d.getDate() + ' ' + MONTHS[d.getMonth()], tone: '' };
}

/** "17 Aug 10:15" from an ISO timestamp (local zone). */
export function fmtTs(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + hh + ':' + mm;
}

// ------------------------------------------------------------------ chips
// Anything that looks like a target inside free text becomes a chip: URLs
// (clickable, new tab), folder placeholders like {onedrive}/house (a
// taskos://open?ref=… link the per-PC opener handles — Step 9), owner/repo#N
// issue refs (GitHub link — Step 8 makes them provider-aware).
const TOKEN_RE = /(https?:\/\/[^\s<>"')\]]+|mailto:[^\s<>"']+|\{[a-z][a-z0-9:_-]*\}[^\s<>"']*|\b[\w.-]+\/[\w.-]+#\d+\b)/g;

function chipEl(kind, label, href) {
  const el = document.createElement(href ? 'a' : 'span');
  el.className = 'chip chip-' + kind;
  if (href) {
    el.href = href;
    if (kind !== 'folder') {
      el.target = '_blank';
      el.rel = 'noopener';
    }
  }
  el.innerHTML = icon(kind === 'folder' ? 'folder' : (kind === 'issue' ? 'git-branch' : (kind === 'email' ? 'mail' : 'link')));
  const t = document.createElement('span');
  t.className = 'chip-label';
  t.textContent = label;
  el.appendChild(t);
  el.title = href || label;
  return el;
}

function shortUrl(u) {
  try {
    const url = new URL(u);
    const path = url.pathname.replace(/\/$/, '');
    const s = url.host + (path && path !== '/' ? path : '');
    return s.length > 42 ? s.slice(0, 40) + '…' : s;
  } catch (_) {
    return u.length > 42 ? u.slice(0, 40) + '…' : u;
  }
}

// ------------------------------------------------------- folder chips
// A folder ref is a link the browser hands to the per-PC opener
// (taskos://open?ref=…, opener/README.md). The page never resolves a ref
// itself: `resolved` is the server's absolute path (this install's
// placeholders) and is only ever shown — as the tooltip, in the copy popover.
// Coarse pointer (phone): no Explorer to open, so the click shows the path
// to copy (+ the web URL when the task carries one). Fine pointer: the link
// goes to the opener, and once — the first click ever on this browser — a
// hint appears under the chip: "Nothing opened? Install the opener".
const HINT_KEY = 'task-os.opener-hint';
export const OPENER_SCHEME = 'taskos://open?ref=';

export function openerHref(ref) {
  return OPENER_SCHEME + encodeURIComponent(String(ref || ''));
}

let pop = null;
function popEl() {
  if (pop) return pop;
  pop = document.createElement('div');
  pop.id = 'folderPop';
  pop.className = 'folder-pop card';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Folder');
  pop.hidden = true;
  document.body.appendChild(pop);
  document.addEventListener('click', function (ev) {
    if (!pop.hidden && !pop.contains(ev.target) && !ev.target.closest('.chip-folder')) hideFolderPopover();
  });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') hideFolderPopover(); });
  window.addEventListener('scroll', hideFolderPopover, true);
  window.addEventListener('resize', hideFolderPopover);
  return pop;
}

export function hideFolderPopover() {
  if (pop) pop.hidden = true;
}

/** Clipboard write with the button flashing "Copied" (exported for the drawer + Settings). */
export async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const prev = btn.innerHTML;
      btn.innerHTML = icon('check') + ' Copied';
      setTimeout(function () { btn.innerHTML = prev; }, 1200);
    }
  } catch (_) {
    if (btn) btn.textContent = 'Copy failed';
  }
}

/**
 * Show the folder popover under `anchor`.
 * @param {HTMLElement} anchor
 * @param {{ref: string, resolved?: string|null, url?: string|null}} info
 * @param {'copy'|'hint'} mode  copy = the path to copy (phone / no opener);
 *                              hint = "Nothing opened? Install the opener" (once, desktop)
 */
export function showFolderPopover(anchor, info, mode) {
  const el = popEl();
  el.innerHTML = '';
  el.dataset.mode = mode;
  const path = info.resolved || info.ref;
  if (mode === 'hint') {
    const p = document.createElement('p');
    p.className = 'folder-pop-hint';
    p.appendChild(document.createTextNode('Nothing opened? '));
    const a = document.createElement('a');
    a.href = '#settings/opener';
    a.className = 'folder-pop-install';
    a.textContent = 'Install the opener — 30 s';
    a.addEventListener('click', function () { hideFolderPopover(); });
    p.appendChild(a);
    p.appendChild(document.createTextNode(' — the browser asks once, then Explorer opens the folder on this PC.'));
    el.appendChild(p);
  } else {
    const t = document.createElement('p');
    t.className = 'folder-pop-title';
    t.textContent = info.resolved ? 'Folder — path on the server PC' : 'Folder ref';
    el.appendChild(t);
  }
  const code = document.createElement('code');
  code.className = 'folder-pop-path';
  code.textContent = path;
  el.appendChild(code);
  const row = document.createElement('div');
  row.className = 'folder-pop-actions';
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'button-surface folder-pop-copy';
  copy.innerHTML = icon('copy') + ' Copy path';
  copy.addEventListener('click', function () { copyText(path, copy); });
  row.appendChild(copy);
  if (info.url) {
    const web = document.createElement('a');
    web.className = 'button-ghost';
    web.href = info.url;
    web.target = '_blank';
    web.rel = 'noopener';
    web.innerHTML = icon('globe') + ' Open web link';
    row.appendChild(web);
  }
  el.appendChild(row);
  el.hidden = false;
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth || 320;
  const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
  let top = r.bottom + 6;
  if (top + el.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - el.offsetHeight - 6);
  el.style.left = left + 'px';
  el.style.top = top + 'px';
}

/**
 * The folder chip: `<a class="chip chip-folder" href="taskos://open?ref=…" title="<resolved>">`.
 * @param {string} ref                    the unresolved ref ({onedrive}/…)
 * @param {{resolved?: string|null, url?: string|null, label?: string|null}} [opts]
 */
export function folderChip(ref, opts) {
  const o = opts || {};
  const info = { ref: String(ref || ''), resolved: o.resolved || null, url: o.url || null };
  const el = chipEl('folder', o.label || info.ref, openerHref(info.ref));
  el.title = info.resolved || info.ref;
  el.dataset.ref = info.ref;
  if (info.resolved) el.dataset.resolved = info.resolved;
  el.addEventListener('click', function (ev) {
    ev.stopPropagation();          // never also opens the row's drawer
    if (window.matchMedia('(pointer: coarse)').matches) {
      ev.preventDefault();
      showFolderPopover(el, info, 'copy');
      return;
    }
    let seen = false;
    try { seen = localStorage.getItem(HINT_KEY) === '1'; } catch (_) { /* private mode */ }
    if (!seen) {
      try { localStorage.setItem(HINT_KEY, '1'); } catch (_) { /* private mode */ }
      setTimeout(function () { showFolderPopover(el, info, 'hint'); }, 350);
    }
  });
  return el;
}

/** Build a chip for one target string, kind inferred from its shape.
 *  `opts` (folder refs only): {resolved, url} from the task payload. */
export function chipFor(target, label, opts) {
  const t = String(target || '');
  if (/^https?:\/\//i.test(t)) {
    const issue = /github\.com\/([^/]+\/[^/]+)\/issues\/(\d+)/.exec(t);
    if (issue) return chipEl('issue', label || (issue[1] + '#' + issue[2]), t);
    return chipEl('web', label || shortUrl(t), t);
  }
  if (/^mailto:/i.test(t)) return chipEl('email', label || t.slice(7), t);
  if (/^mail:\/\//i.test(t)) return chipEl('email', label || t.slice(7), null);
  if (/^\{/.test(t)) return folderChip(t, Object.assign({ label: label || null }, opts || {}));
  const m = /^([\w.-]+\/[\w.-]+)#(\d+)$/.exec(t);
  if (m) return chipEl('issue', label || t, 'https://github.com/' + m[1] + '/issues/' + m[2]);
  return chipEl('web', label || t, null);
}

/** Text with its targets rendered as chips → DocumentFragment. */
export function linkify(text) {
  const frag = document.createDocumentFragment();
  const s = String(text == null ? '' : text);
  let last = 0;
  s.replace(TOKEN_RE, function (match, _g, offset) {
    if (offset > last) frag.appendChild(document.createTextNode(s.slice(last, offset)));
    // strip trailing punctuation from a URL match
    let core = match;
    let tail = '';
    const p = /[.,;:!?]+$/.exec(core);
    if (p && !/^\{/.test(core)) { core = core.slice(0, p.index); tail = p[0]; }
    frag.appendChild(chipFor(core));
    if (tail) frag.appendChild(document.createTextNode(tail));
    last = offset + match.length;
    return match;
  });
  if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
  return frag;
}

// --------------------------------------------------------------- markdown
/** A small, safe markdown subset: headings, lists, code, bold/italic, links, paragraphs. */
export function renderMarkdown(md) {
  const lines = String(md == null ? '' : md).replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let list = null;
  let code = false;
  let para = [];
  function inline(t) {
    let h = escapeHtml(t);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/(^|\W)\*([^*]+)\*(?=\W|$)/g, '$1<em>$2</em>');
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    return h;
  }
  function flushPara() {
    if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; }
  }
  function flushList() {
    if (list) { out.push('</' + list + '>'); list = null; }
  }
  lines.forEach(function (raw) {
    const line = raw.replace(/\s+$/, '');
    if (/^```/.test(line)) {
      flushPara(); flushList();
      out.push(code ? '</code></pre>' : '<pre><code>');
      code = !code;
      return;
    }
    if (code) { out.push(escapeHtml(line) + '\n'); return; }
    if (!line.trim()) { flushPara(); flushList(); return; }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) { flushPara(); flushList(); out.push('<h' + (h[1].length + 2) + '>' + inline(h[2]) + '</h' + (h[1].length + 2) + '>'); return; }
    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ul || ol) {
      flushPara();
      const want = ul ? 'ul' : 'ol';
      if (list !== want) { flushList(); list = want; out.push('<' + want + '>'); }
      out.push('<li>' + inline((ul || ol)[1]) + '</li>');
      return;
    }
    flushList();
    para.push(line);
  });
  flushPara(); flushList();
  if (code) out.push('</code></pre>');
  return out.join('');
}

// ------------------------------------------------------------------ misc
export function statusPill(status) {
  const el = document.createElement('span');
  el.className = 'pill pill-' + (status || 'inbox');
  el.textContent = status || 'inbox';
  return el;
}

export function priorityLabel(p) {
  return p && p !== 'none' ? p : '—';
}

export function breadcrumbText(crumbs) {
  return (crumbs || []).map(function (c) { return c.title; }).join(' › ');
}
