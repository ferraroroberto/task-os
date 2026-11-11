/* On-device probe for the top of the page: what paints over the header card.
 *
 * Desktop engines do not reproduce how the installed iOS app composites the
 * nav's glass, so this panel reports, on the phone itself, everything that
 * could blur the header: the stack of elements at its centre with their
 * filters, stacking and masks, every element carrying a filter, the nav's top
 * glass pseudo-element, the page head tags, the viewport and the scroll, and
 * whether the page runs the build the server is serving now.
 *
 * Off unless asked for. `?navdebug=1` turns it on and `?navdebug=0` off, and
 * five quick taps on the build footer toggle it: an installed app cannot open
 * a typed URL. The choice is stored, so a cold relaunch is probed too. The
 * panel is plain text in the page flow below the footer, never fixed and never
 * filtered, so it adds nothing to the layers it reports on. Element names are
 * tag, id and classes only, never text content. */

const STORE_KEY = 'task-os.navdebug';
// Five taps inside this window toggle the probe; slower taps start over.
const TOGGLE_TAPS = 5;
const TOGGLE_WINDOW_MS = 2000;
// Snapshots at these times after load: before, during and after the nav's
// glass settle watch (it runs for 4s after a launch).
const SNAPSHOT_AT_MS = [0, 300, 1000, 5000];
// Kept at-rest snapshots; later ones replace the oldest after the first.
const MAX_SNAPSHOTS = 8;
const STYLE_PROPS = ['backdrop-filter', 'filter', 'z-index', 'position', 'opacity', 'mask-image', 'transform', 'will-change'];

// Read at module load: the app rewrites the query from its filter state once
// the nav restores a tab, which drops this flag.
const QUERY_FLAG = new URLSearchParams(location.search).get('navdebug');

function wanted() {
  const flag = QUERY_FLAG;
  try {
    if (flag === '1') localStorage.setItem(STORE_KEY, '1');
    if (flag === '0') localStorage.removeItem(STORE_KEY);
    return localStorage.getItem(STORE_KEY) === '1';
  } catch (_) {
    return flag === '1';
  }
}

/** Wire the footer toggle, and mount the panel when the probe is on. */
export function wireNavDebug() {
  const on = wanted();
  watchToggle(on);
  if (on) mount();
}

function watchToggle(on) {
  const foot = document.querySelector('.page-foot');
  if (!foot) return;
  let taps = [];
  foot.addEventListener('click', (event) => {
    const now = event.timeStamp;
    taps = taps.filter((t) => now - t < TOGGLE_WINDOW_MS).concat(now);
    if (taps.length < TOGGLE_TAPS) return;
    try {
      if (on) localStorage.removeItem(STORE_KEY);
      else localStorage.setItem(STORE_KEY, '1');
    } catch (_) { /* private mode: only the query flag works */ }
    location.reload();
  });
}

function describe(el) {
  if (!el || !el.tagName) return String(el);
  let name = el.tagName.toLowerCase();
  if (el.id) name += '#' + el.id;
  if (typeof el.className === 'string' && el.className.trim()) name += '.' + el.className.trim().split(/\s+/).join('.');
  return name;
}

function rectOf(el) {
  const r = el.getBoundingClientRect();
  return `[${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}]`;
}

// Only the properties that differ from an unstyled element, so the panel
// stays short enough for one phone screenshot.
function styleOf(el, pseudo) {
  const cs = getComputedStyle(el, pseudo);
  const quiet = { 'backdrop-filter': 'none', filter: 'none', 'z-index': 'auto', position: 'static', opacity: '1', 'mask-image': 'none', transform: 'none', 'will-change': 'auto' };
  const parts = [];
  STYLE_PROPS.forEach((prop) => {
    let value = cs.getPropertyValue(prop) || cs.getPropertyValue('-webkit-' + prop);
    if (!value && prop === 'backdrop-filter') value = cs.webkitBackdropFilter || '';
    if (!value && prop === 'mask-image') value = cs.webkitMaskImage || '';
    value = (value || '').trim();
    if (value && value !== quiet[prop]) parts.push(prop + '=' + value.slice(0, 60));
  });
  return parts.join(' ') || '(plain)';
}

function stackAt(x, y) {
  return document.elementsFromPoint(x, y)
    .filter((el) => el !== document.documentElement)
    // The page containers grow as data loads; their size says nothing about a blur.
    .map((el) => '  ' + describe(el) + (el === document.body || el.matches('main.app') ? '' : ' ' + rectOf(el)) + ' ' + styleOf(el));
}

function filtered() {
  const out = [];
  document.querySelectorAll('*').forEach((el) => {
    const cs = getComputedStyle(el);
    const backdrop = (cs.getPropertyValue('backdrop-filter') || cs.webkitBackdropFilter || 'none').trim();
    const filter = (cs.getPropertyValue('filter') || 'none').trim();
    if (backdrop === 'none' && filter === 'none') return;
    out.push('  ' + describe(el) + ' ' + rectOf(el) + ' vis=' + cs.visibility + ' backdrop=' + backdrop + ' filter=' + filter);
  });
  return out.length ? out : ['  (none)'];
}

function safeTop() {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;top:0;left:0;width:0;visibility:hidden;padding-top:env(safe-area-inset-top,0px)';
  document.body.appendChild(probe);
  const top = getComputedStyle(probe).paddingTop;
  probe.remove();
  return top;
}

function metaOf(name) {
  return [...document.querySelectorAll(`meta[name="${name}"]`)]
    .filter((tag) => !tag.media || matchMedia(tag.media).matches)
    .map((tag) => tag.content).join(' | ') || '(none)';
}

function pageHash() {
  const script = document.querySelector('script[type="module"][src*="app.js"]');
  return script ? (new URL(script.src, location.href).searchParams.get('v') || '(unstamped)') : '(no app.js tag)';
}

function snapshot(served) {
  const root = document.documentElement;
  const head = document.querySelector('.home-head');
  const nav = document.querySelector('.tabs');
  const nav0 = performance.getEntriesByType('navigation')[0];
  const vv = window.visualViewport;
  const lines = [
    `build page=${pageHash()} served=${served} load=${nav0 ? nav0.type : '?'} vis=${document.visibilityState}`,
    `standalone=${matchMedia('(display-mode: standalone)').matches} win=${innerWidth}x${innerHeight} screen=${screen.width}x${screen.height} dpr=${devicePixelRatio}`
      + ` vv=${vv ? Math.round(vv.width) + 'x' + Math.round(vv.height) + '@' + Math.round(vv.offsetTop) : '-'} safeTop=${safeTop()}`,
    `scrollY=${scrollY} glassAttr=${root.hasAttribute('data-nav-top-glass')} fadeOn=${root.style.getPropertyValue('--nav-fade-on') || '-'}`
      + ` navClass=${nav ? nav.className : '-'}`,
    `meta viewport=${metaOf('viewport')}`,
    `meta status=${metaOf('apple-mobile-web-app-status-bar-style')} theme=${metaOf('theme-color')}`,
    `body::after content=${getComputedStyle(document.body, '::after').content} ${styleOf(document.body, '::after')} h=${getComputedStyle(document.body, '::after').height}`,
    `body::before ${styleOf(document.body, '::before')}`,
  ];
  if (head) {
    const r = head.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    lines.push(`header ${rectOf(head)} ${styleOf(head)}`);
    lines.push('stack at header centre:', ...stackAt(cx, r.top + r.height / 2));
    lines.push('stack at header top+4:', ...stackAt(cx, r.top + 4));
  } else {
    lines.push('header: not found');
  }
  lines.push('filtered elements:', ...filtered());
  return lines.join('\n');
}

function mount() {
  const panel = document.createElement('section');
  panel.className = 'navdebug';
  panel.setAttribute('aria-label', 'Nav diagnostics');
  panel.style.cssText = 'margin:16px 0;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);'
    + 'font:10px/1.35 ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-all;-webkit-user-select:text;user-select:text';
  const pre = document.createElement('div');
  panel.appendChild(pre);
  (document.querySelector('main.app') || document.body).appendChild(panel);

  let served = 'fetching';
  // Each kept reading is { reasons, body }: a reading identical to the one
  // before it only adds its reason, so the panel fits a phone screenshot.
  const rest = [];
  let live = '';
  const render = () => {
    pre.textContent = 'NAV DEBUG (5 taps on the build line turns it off)\n'
      + rest.map((r) => '-- ' + r.reasons.join(', ') + '\n' + r.body).join('\n') + '\n== now\n' + live;
  };
  const keep = (reason) => {
    // At-rest readings are the ones that matter: the header is blurred with no scroll.
    if (scrollY !== 0 && reason !== 'load') return;
    const body = snapshot(served);
    const last = rest.at(-1);
    const stamp = `${reason} t=${Math.round(performance.now())}ms`;
    if (last && last.body === body) last.reasons.push(stamp);
    else {
      if (rest.length >= MAX_SNAPSHOTS) rest.splice(1, 1);
      rest.push({ reasons: [stamp], body });
    }
    render();
  };
  const fetchServed = () => fetch('/api/version', { cache: 'no-store' })
    .then((res) => res.json())
    .then((v) => { served = `${v.git_sha}/${v.asset_hash}`; })
    .catch((err) => { served = 'unknown (' + err.message + ')'; })
    .then(() => keep('served-fetched'));

  SNAPSHOT_AT_MS.forEach((ms) => setTimeout(() => keep(ms ? `+${ms}ms` : 'load'), ms));
  fetchServed();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') { fetchServed(); setTimeout(() => keep('resumed+1s'), 1000); }
  });
  window.addEventListener('pageshow', (event) => { if (event.persisted) keep('pageshow-bfcache'); });
  let frame = 0;
  window.addEventListener('scroll', () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      live = `scrollY=${scrollY} glassAttr=${document.documentElement.hasAttribute('data-nav-top-glass')}`
        + ` fadeOn=${document.documentElement.style.getPropertyValue('--nav-fade-on') || '-'}`;
      if (scrollY === 0) keep('back-at-top');
      else render();
    });
  }, { passive: true });
}
