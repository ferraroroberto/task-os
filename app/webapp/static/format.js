/* task-os — formatting helpers shared by the Table, Tree and drawer.
 *
 * Relative dates, timestamps, link chips (URLs / folder placeholders /
 * repo#N inside comment bodies) and a deliberately small markdown renderer
 * for descriptions. Everything escapes text before it touches innerHTML.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { api } from './api.js';

export const STATUSES = ['inbox', 'todo', 'doing', 'standby', 'done', 'cancelled'];
export const PRIORITIES = ['high', 'medium', 'low', 'none'];
export const RECURRENCES = ['', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'];

/* Fixed-day anchors (#112) — the cadences that take one, and the options each
 * offers. The canonical spellings and the wording below mirror
 * src/dates.py::normalise_anchor / describe_recurrence; the server is the
 * authority, this is the picker's copy of the same vocabulary. */
const WEEKDAY_ABBR = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const WEEKDAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const ORDINAL_WORDS = { 1: 'first', 2: 'second', 3: 'third', 4: 'fourth', last: 'last' };

/** The anchor picker's option groups for a cadence — `[]` when it takes none.
 *
 * `[{label, options: [[value, text], …]}]`; the first group is unlabelled and
 * holds the "no anchor" choice, so the picker always offers a way back to the
 * plain offset roll. The 66 monthly values are grouped rather than flat: a
 * native select is a scrollable list on the phone, and "Day of month" /
 * "Weekday" split it into two readable halves.
 */
export function anchorOptions(recurrence) {
  if (recurrence === 'weekly') {
    return [
      { options: [['', 'any day (offset from the due date)']] },
      {
        label: 'Every',
        options: [['mon,tue,wed,thu,fri', 'weekday (Mon–Fri)']].concat(
          WEEKDAY_ABBR.map(function (abbr, i) { return [abbr, WEEKDAY_FULL[i]]; })
        ),
      },
    ];
  }
  if (recurrence === 'monthly') {
    const days = [];
    for (let d = 1; d <= 31; d++) days.push(['day-' + d, 'the ' + ordinal(d)]);
    const nths = [];
    ['1', '2', '3', '4', 'last'].forEach(function (n) {
      WEEKDAY_ABBR.forEach(function (abbr, i) {
        nths.push([n + '-' + abbr, 'the ' + ORDINAL_WORDS[n] + ' ' + WEEKDAY_FULL[i]]);
      });
    });
    return [
      { options: [['', 'same day each month']] },
      { label: 'Day of month', options: days },
      { label: 'Weekday', options: nths },
    ];
  }
  return [];
}

function ordinal(n) {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th'
    : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th';
  return n + suffix;
}

/** The label for a cadence + anchor — 'every Friday', 'monthly on the 15th', 'weekly'. */
export function recurrenceLabel(recurrence, anchor) {
  if (!recurrence) return '';
  if (!anchor) return recurrence;
  if (recurrence === 'weekly') {
    const days = String(anchor).split(',');
    if (anchor === 'mon,tue,wed,thu,fri') return 'every weekday';
    const names = days.map(function (d) { return WEEKDAY_FULL[WEEKDAY_ABBR.indexOf(d)] || d; });
    return 'every ' + (names.length > 1
      ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]
      : names[0]);
  }
  const day = /^day-(\d{1,2})$/.exec(anchor);
  if (day) return 'monthly on the ' + ordinal(Number(day[1]));
  const nth = /^(1|2|3|4|last)-([a-z]+)$/.exec(anchor);
  if (nth) {
    return 'monthly on the ' + ORDINAL_WORDS[nth[1]] + ' '
      + (WEEKDAY_FULL[WEEKDAY_ABBR.indexOf(nth[2])] || nth[2]);
  }
  return recurrence;
}

const DAY_MS = 86400000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

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

/**
 * Is this task still asleep? — a `starts` date the current local day has not
 * reached yet (#87). The ONE place the browser answers that question, so the
 * row marker, the drawer label and the client-side filter agree.
 * @param {object} t     a task summary or detail
 * @param {string} [now] ISO date (tests)
 */
export function isDeferred(t, now) {
  return !!(t && t.starts) && t.starts > todayISO(now ? new Date(now + 'T00:00:00') : undefined);
}

/** Is this task blocked right now? — it has at least one still-open blocker
 *  (#100). The ONE place the browser answers that question, so the row
 *  marker, the drawer and the client-side filter agree — mirrors `isDeferred`.
 * @param {object} t   a task summary or detail (carries `blocked` server-side)
 */
export function isBlocked(t) {
  return !!(t && t.blocked);
}

/** "blocked by 2" — the meta-line marker a locked task wears (#100). */
export function blockedLabel(t) {
  const n = (t && t.blocker_count) || 0;
  return 'blocked by ' + n;
}

/** "starts 5 Sep" — the quiet marker a sleeping task wears (#87). */
export function startsLabel(iso) {
  const d = parseISO(iso);
  return d ? 'starts ' + d.getDate() + ' ' + MONTHS[d.getMonth()] : '';
}

/** "Sat 5 Sep" — a date named the way a confirmation should name it (#87):
 *  the weekday is what makes "this weekend" checkable at a glance. */
export function fmtDay(iso) {
  const d = parseISO(iso);
  return d ? DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()] : '';
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

/** The locale's short date + time from an ISO timestamp — the status-line
 *  stamp the Settings cards and the header ↻ tooltip use. */
export function fmtTsShort(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

// ------------------------------------------------------------------ chips
// Anything that looks like a target inside free text becomes a chip: URLs
// (clickable, new tab), folder placeholders like {onedrive}/house (a
// taskos://open?ref=… link the per-PC opener handles — Step 9), owner/repo#N
// issue refs (GitHub link — Step 8 makes them provider-aware).
const TOKEN_RE = /(https?:\/\/[^\s<>"')\]]+|mailto:[^\s<>"']+|\{[a-z][a-z0-9:_-]*\}[^\s<>"']*|\b[\w.-]+\/[\w.-]+#\d+\b)/g;

function chipEl(kind, label, href, iconName) {
  const el = document.createElement(href ? 'a' : 'span');
  el.className = 'chip chip-' + kind;
  if (href) {
    el.href = href;
    if (kind !== 'folder') {
      el.target = '_blank';
      el.rel = 'noopener';
    }
  }
  el.innerHTML = icon(iconName || (kind === 'folder' ? 'folder' : (kind === 'issue' ? 'git-branch' : (kind === 'email' ? 'mail' : 'link'))));
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
// Coarse pointer (phone): no Explorer to open, so the tap opens the chip's
// web twin directly — the carried `url`, else one resolved on demand from
// POST /api/resolve (web_roots, #28/#72); only a ref with no web twin at all
// falls back to the path-to-copy popover. Fine pointer: the link goes to the
// opener, and once — the first click ever on this browser — a hint appears
// under the chip: "Nothing opened? Install the opener".
const HINT_KEY = 'task-os.opener-hint';
export const OPENER_SCHEME = 'taskos://open?ref=';

export function openerHref(ref) {
  return OPENER_SCHEME + encodeURIComponent(String(ref || ''));
}

/** The chip's web twin, established once per chip: the `url` it carries, else
 *  what POST /api/resolve derives from config.web_roots (#28) — null when
 *  neither. Link chips (a .msg email ref, an attached file) never carry a
 *  url, so the on-demand resolve is what gives them a one-tap open (#72). */
async function chipWebUrl(info) {
  if (info.url) return info.url;
  if (info.webChecked) return null;
  info.webChecked = true;
  try {
    const r = await api('/api/resolve', { method: 'POST', body: { ref: info.ref } });
    info.url = r.web_url || null;
  } catch (_) { info.url = null; }
  return info.url;
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
    if (!pop.hidden && !pop.contains(ev.target) && !ev.target.closest('.chip-folder, .chip-ai')) hideFolderPopover();
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
 * @param {{resolved?: string|null, url?: string|null, label?: string|null, icon?: string}} [opts]
 *        `icon` swaps the glyph (an email link's .msg ref opens through the same opener — mail glyph)
 */
export function folderChip(ref, opts) {
  const o = opts || {};
  const info = { ref: String(ref || ''), resolved: o.resolved || null, url: o.url || null };
  const el = chipEl('folder', o.label || info.ref, openerHref(info.ref), o.icon || null);
  el.title = info.resolved || info.ref;
  el.dataset.ref = info.ref;
  if (info.resolved) el.dataset.resolved = info.resolved;
  el.addEventListener('click', function (ev) {
    ev.stopPropagation();          // never also opens the row's drawer
    if (window.matchMedia('(pointer: coarse)').matches) {
      ev.preventDefault();
      if (info.url) { window.open(info.url, '_blank', 'noopener'); return; }
      chipWebUrl(info).then(function (url) {
        if (url) {
          // an async window.open can be popup-blocked — fall back to navigating
          if (!window.open(url, '_blank', 'noopener')) location.assign(url);
        } else {
          showFolderPopover(el, info, 'copy');
        }
      });
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

// --------------------------------------------------------- AI conversation chips
// One kind for every provider (#77) — a Claude Code / claude.ai / ChatGPT /
// Gemini / Copilot conversation URL gets the same bot chip, no per-provider
// split. Coarse pointer: the tap opens the conversation (new tab) — on a phone
// there is no CLI to resume into. Fine pointer: a popover offers "Open
// conversation" (the usual choice) and, for a Claude Code session, "Resume in
// CLI on this PC" through the same per-PC opener the folder chips use
// (taskos://resume?session=…): the opener finds the local transcript and
// reopens the session in a terminal, falling back to the web page when this PC
// never saw that session.
export const AI_URL_RE = /^https?:\/\/(?:www\.)?(?:claude\.ai\/|chatgpt\.com\/|chat\.openai\.com\/|gemini\.google\.com\/|copilot\.microsoft\.com\/|github\.com\/copilot(?:\/|$))/i;
const CLAUDE_SESSION_RE = /claude\.ai\/code\/(session_[A-Za-z0-9]+)/;
export const RESUME_SCHEME = 'taskos://resume?session=';

/** The `kind` a pasted link is stored under — one rule, wherever a link is
 *  added (the drawer's Links section and the quick-add dialog, #80 round 2). */
export function linkKind(url) {
  if (/^\{/.test(url)) return 'folder';
  if (/^mail(to:|:\/\/)/i.test(url)) return 'email';
  if (AI_URL_RE.test(url)) return 'ai';
  if (/github\.com\/[^/]+\/[^/]+\/issues\/\d+/.test(url)) return 'issue';
  return 'web';
}

function showAiPopover(anchor, url) {
  const el = popEl();
  el.innerHTML = '';
  el.dataset.mode = 'ai';
  const t = document.createElement('p');
  t.className = 'folder-pop-title';
  t.textContent = 'AI conversation';
  el.appendChild(t);
  const row = document.createElement('div');
  row.className = 'folder-pop-actions';
  const web = document.createElement('a');
  web.className = 'button-surface ai-pop-open';
  web.href = url;
  web.target = '_blank';
  web.rel = 'noopener';
  web.innerHTML = icon('external-link') + ' Open conversation';
  web.addEventListener('click', hideFolderPopover);
  row.appendChild(web);
  const session = CLAUDE_SESSION_RE.exec(url);
  if (session) {
    const cli = document.createElement('a');
    cli.className = 'button-ghost ai-pop-resume';
    cli.href = RESUME_SCHEME + encodeURIComponent(session[1]);
    cli.innerHTML = icon('terminal') + ' Resume in CLI on this PC';
    cli.title = 'Reopens the session in a terminal via the task-os opener; falls back to the web page if this PC never saw it';
    cli.addEventListener('click', hideFolderPopover);
    row.appendChild(cli);
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

/** The AI-conversation chip: bot glyph, opens on tap (phone) or via the
 *  open/resume popover (desktop). */
export function aiChip(url, label) {
  const el = chipEl('ai', label || 'AI chat', url, 'bot');
  el.addEventListener('click', function (ev) {
    ev.stopPropagation();          // never also opens the row's drawer
    if (window.matchMedia('(pointer: coarse)').matches) return;   // plain link → new tab
    ev.preventDefault();
    showAiPopover(el, url);
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
    if (AI_URL_RE.test(t)) return aiChip(t, label);
    return chipEl('web', label || shortUrl(t), t);
  }
  if (/^mailto:/i.test(t)) return chipEl('email', label || t.slice(7), t);
  if (/^mail:\/\//i.test(t)) return chipEl('email', label || t.slice(7), null);
  if (/^\{/.test(t)) return folderChip(t, Object.assign({ label: label || null }, opts || {}));
  const m = /^([\w.-]+\/[\w.-]+)#(\d+)$/.exec(t);
  if (m) return chipEl('issue', label || t, 'https://github.com/' + m[1] + '/issues/' + m[2]);
  return chipEl('web', label || t, null);
}

/** The chip for a task's issue_ref: provider glyph, repo#N, state on the
 *  chip (open = accent, closed = muted + check) — opens the issue's URL. */
export function issueChip(ref) {
  // short repo name on the chip (cards are narrow); the full owner/repo#N in the title
  const label = String(ref.repo || '').split('/').pop() + '#' + ref.number;
  const href = ref.url || issueUrl(ref.provider, ref.repo, ref.number);
  const el = document.createElement('a');
  const state = ref.state === 'closed' ? 'closed' : (ref.state === 'open' ? 'open' : 'unknown');
  el.className = 'chip chip-issue chip-issue-' + state;
  el.href = href;
  el.target = '_blank';
  el.rel = 'noopener';
  el.innerHTML = icon(providerIcon(ref.provider));
  const t = document.createElement('span');
  t.className = 'chip-label';
  t.textContent = label;
  el.appendChild(t);
  if (state === 'closed') el.innerHTML += icon('circle-check', 'chip-state');
  el.title = ref.repo + '#' + ref.number + ' · ' + (ref.state || 'state unknown') + (ref.last_synced ? ' · synced ' + fmtTs(ref.last_synced) : '');
  el.dataset.state = state;
  return el;
}

export function providerIcon(provider) {
  return provider === 'github' ? 'github' : 'git-branch';
}

export function issueUrl(provider, repo, number) {
  const host = provider === 'gitlab' ? 'https://gitlab.com/' : 'https://github.com/';
  return host + repo + (provider === 'gitlab' ? '/-/issues/' : '/issues/') + number;
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
