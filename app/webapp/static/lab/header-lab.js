// Header variant lab — temporary. Wires the lab page: the shell's own nav
// (vendored, so the bar behaves as in the app), the variant buttons, the
// facts line the owner's screenshot carries, and the filler rows that scroll
// under the glass. The variant itself is already on <html data-v> from the
// head script; this file only reads it.

import { initNavTabs } from '../_vendored/nav/nav-tabs.js';

const VARIANTS = [
  'Control: the app\'s styles unchanged',
  'Nav: no backdrop-filter, opaque card surface',
  'Nav: -webkit-backdrop-filter only',
  'Nav: unprefixed backdrop-filter only',
  'Nav: blur 8px instead of 24px',
  'Nav: glass on a pseudo-element behind the bar',
  'No translateZ / will-change / backface in header or nav',
  'Header card position: sticky (nav stays fixed)',
  'Text: font-smoothing antialiased + geometricPrecision',
  'No scroll-edge fade bands (top and bottom)',
  'Header card on its own layer (translateZ)',
  'No 1px viewport-expanding scroll at launch',
];

const root = document.documentElement;
const variant = Number(root.dataset.v) || 1;

function displayMode() {
  for (const mode of ['standalone', 'fullscreen', 'minimal-ui', 'browser']) {
    if (window.matchMedia('(display-mode: ' + mode + ')').matches) return mode;
  }
  return 'unknown';
}

// iOS 26 Safari freezes the OS token in the UA string, so the Safari
// Version/ token (which tracks the iOS release) is shown beside it.
function osFacts() {
  const ua = navigator.userAgent;
  const os = ua.match(/OS (\d+(?:_\d+)*) like Mac OS X/);
  const safari = ua.match(/Version\/(\d+(?:\.\d+)*)/);
  const parts = [os ? 'UA iOS ' + os[1].replace(/_/g, '.') : 'UA not iOS'];
  if (safari) parts.push('Safari ' + safari[1]);
  return parts.join(' · ');
}

function navFilters() {
  const style = getComputedStyle(document.querySelector('.tabs'));
  const webkit = style.getPropertyValue('-webkit-backdrop-filter') || 'unset';
  const plain = style.getPropertyValue('backdrop-filter') || 'unset';
  return 'nav bf ' + plain + ' / -webkit- ' + webkit;
}

function renderFacts() {
  const vv = window.visualViewport;
  const viewport = window.innerWidth + '×' + window.innerHeight
    + (vv ? ' (visual ' + Math.round(vv.width) + '×' + Math.round(vv.height) + ')' : '');
  document.getElementById('labFacts').textContent = [
    'v' + variant,
    osFacts(),
    'display-mode ' + displayMode(),
    'DPR ' + window.devicePixelRatio,
    'viewport ' + viewport,
    'theme ' + root.dataset.theme,
    navFilters(),
  ].join(' · ');
}

function renderVariants() {
  document.getElementById('labLabel').textContent = variant + '. ' + VARIANTS[variant - 1];
  const host = document.getElementById('labVariants');
  VARIANTS.forEach(function (label, i) {
    const link = document.createElement('a');
    link.className = 'lab-variant';
    link.href = '?v=' + (i + 1);
    link.textContent = String(i + 1);
    link.title = label;
    link.setAttribute('aria-label', (i + 1) + '. ' + label);
    link.dataset.track = 'lab.variant';
    if (i + 1 === variant) link.setAttribute('aria-current', 'true');
    host.appendChild(link);
  });
}

// Enough rows to scroll well past the bar, with tinted words so the glass
// has colour to blur.
function renderRows() {
  const host = document.getElementById('labRows');
  for (let i = 1; i <= 30; i += 1) {
    const card = document.createElement('div');
    card.className = 'card lab-row';
    card.innerHTML = '<p class="lab-row-title">Sample row ' + i + ' with a long enough title to wrap</p>'
      + '<p class="lab-row-meta"><b>Due today</b> · project ' + ((i % 4) + 1) + ' · scroll under the bar</p>';
    host.appendChild(card);
  }
}

function wireTheme() {
  document.getElementById('themeToggle').addEventListener('click', function () {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('task-os.theme', next); } catch (e) { /* private mode: this page only */ }
    renderFacts();
  });
  document.getElementById('labReload').addEventListener('click', function () {
    location.reload();
  });
}

// Variant 12 runs the nav's start-up without its 1px viewport-expanding
// scroll: window.scrollTo is a no-op only while initNavTabs runs.
function initNav() {
  if (variant !== 12) {
    initNavTabs({ storageKey: null });
    return;
  }
  const scrollTo = window.scrollTo;
  window.scrollTo = function () {};
  try {
    initNavTabs({ storageKey: null });
  } finally {
    window.scrollTo = scrollTo;
  }
}

renderVariants();
renderRows();
wireTheme();
initNav();
renderFacts();
window.addEventListener('resize', renderFacts, { passive: true });
if (window.visualViewport) window.visualViewport.addEventListener('resize', renderFacts, { passive: true });
