// Header offset lab — temporary. Wires the lab page: the shell's own nav
// (vendored, so the bar behaves as in the app), the variant buttons, the
// facts line the owner's screenshot carries, and the filler rows that scroll
// under the glass. The variant itself is already on <html data-v> from the
// head script; this file only reads it.

import { initNavTabs } from '../_vendored/nav/nav-tabs.js';

// [button caption, description]; the offset rides on top of the safe-area
// inset the app already reserves, and the CSS owns the numbers.
const VARIANTS = [
  ['0px', 'Control: the app\'s styles unchanged (+0px)'],
  ['2px', 'Content starts 2px lower'],
  ['4px', 'Content starts 4px lower'],
  ['6px', 'Content starts 6px lower'],
  ['8px', 'Content starts 8px lower'],
  ['12px', 'Content starts 12px lower'],
  ['16px', 'Content starts 16px lower'],
  ['20px', 'Content starts 20px lower'],
  ['24px', 'Content starts 24px lower'],
  ['32px', 'Content starts 32px lower'],
  ['44px', 'Content starts 44px lower'],
  ['bar y0', 'Status-bar spacer above the header, first frame at y = 0 (header lower)'],
  ['bar ↓', 'Status-bar spacer above the header, first frame scrolled past it (header where the control is)'],
];
const FIRST_FRAME_PAST_SPACER = 13;

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

function px(value) {
  return Math.round(value * 100) / 100 + 'px';
}

function renderFacts() {
  const vv = window.visualViewport;
  const viewport = window.innerWidth + '×' + window.innerHeight
    + (vv ? ' (visual ' + Math.round(vv.width) + '×' + Math.round(vv.height) + ')' : '');
  const safeTop = document.getElementById('labSafeProbe').getBoundingClientRect().height;
  const padTop = parseFloat(getComputedStyle(document.querySelector('main.app')).paddingTop) || 0;
  document.getElementById('labFacts').textContent = [
    'v' + variant,
    osFacts(),
    'display-mode ' + displayMode(),
    'DPR ' + window.devicePixelRatio,
    'viewport ' + viewport,
    'safe-area-top ' + px(safeTop),
    'content padding-top ' + px(padTop),
    'theme ' + root.dataset.theme,
  ].join(' · ');
}

function renderVariants() {
  document.getElementById('labLabel').textContent = variant + '. ' + VARIANTS[variant - 1][1];
  const host = document.getElementById('labVariants');
  VARIANTS.forEach(function (entry, i) {
    const link = document.createElement('a');
    link.className = 'lab-variant';
    link.href = '?v=' + (i + 1);
    link.textContent = String(i + 1);
    const caption = document.createElement('small');
    caption.textContent = entry[0];
    link.appendChild(caption);
    link.title = entry[1];
    link.setAttribute('aria-label', (i + 1) + '. ' + entry[1]);
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

// Runs right after the nav's start-up, whose 1px viewport-claiming scroll
// goes back to the top on the next frame only while scrollY is still 1, so
// this scroll past the spacer stands and the claim is still made.
function startPastSpacer() {
  window.scrollTo(0, document.getElementById('labSpacer').offsetHeight);
}

renderVariants();
renderRows();
wireTheme();
initNavTabs({ storageKey: null });
if (variant === FIRST_FRAME_PAST_SPACER) startPastSpacer();
renderFacts();
window.addEventListener('resize', renderFacts, { passive: true });
if (window.visualViewport) window.visualViewport.addEventListener('resize', renderFacts, { passive: true });
