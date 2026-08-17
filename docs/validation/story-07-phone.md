# Story 07 — Phone

**Issue:** #8 (Step 7/13). **Test:** `tests/e2e/test_story_07_phone.py` (2 tests: the phone story in WebKit device emulation — 390×844 touch, a 430×932 leg, the geometry matrix at 320 / 390 / 430 / 772 — and the `/login` walk against a disposable instance whose temp config carries a token, plus a 1440×900 Chromium shot of the login page), against the **seeded** disposable instance (`tests/fixtures/seed.py`, synthetic data only). Unit coverage for the gate: `tests/test_auth.py` (loopback passes with no credential; a spoofed non-loopback client gets `401` on `/api/*` and a `302 → /login?next=…` on a page; the bearer header passes; `/api/login` with the token or the password sets the 90-day HttpOnly cookie that then passes and `/api/logout` clears; no token configured = the gate is closed for non-loopback and `/api/login` says `503`; token rotation signs the cookie out; `save_auth` creates the real config from the sample and never writes the sample; PBKDF2 hash round-trip; the `gen_token.py` / `set_password.py` scripts end to end).

**Steps → expected**

1. **Install metadata** (what a phone reads before *Add to Home Screen*): `<link rel=manifest>` → `/static/manifest.webmanifest` answers 200 with `name task-os`, `display standalone`, `start_url /`, icons 192 · 512 · 512-maskable — every icon URL answers 200 `image/png`; the shell carries `apple-mobile-web-app-capable=yes`, `apple-mobile-web-app-title=task-os`, an `apple-touch-icon` (200), a viewport with `viewport-fit=cover`, and `theme-color`.
2. Fresh phone (390 wide, touch, nothing persisted) → the app **lands on Today**; no horizontal overflow.
3. Quick-add from Today: type `Water the balcony plants today` → the parsed preview chip shows, Enter → toast `Added #N …`, the row appears in Today's due list; `GET /api/tasks/N` has the title and a due date.
4. Board tab: the columns are a **scroll-snap carousel** opened on *Todo*, exactly one column in view; a **swipe** (a scroll of one column width) makes *Doing* the active strip button and the only column in view; the five strip buttons ≥ 44 px, non-overlapping.
5. Tap the strip to the column holding *Kitchen* → its card shows the folder chip `{onedrive}/house/kitchen` → tap the card → the drawer opens **full-screen** (`#task/2`, the drawer's box is the whole viewport) → the Links section shows the folder chip *Kitchen folder* as a **display-only** chip: a `span` (no `href`), the unresolved ref `{onedrive}/house/kitchen` as its tooltip — the per-PC opener is Step 9; the close button ≥ 44 px.
6. Theme toggle → dark; a reload keeps dark and keeps Today as the tab.
7. 430 wide: the same carousel, one column as wide as the container, exactly one in view.
8. Geometry across 320 / 390 / 430 / 772: no horizontal overflow on Today and the Board; the vendored nav is the floating pill (fixed) below 772 and the desktop segmented control at 772; pill tabs ≥ 44 px from 390 up (six tabs at 320 are ~42 px across — the vendored component's own auto-fit — the height floor holds), never overlapping; the Board strip ≥ 44 px everywhere.
9. `/login` on the phone renders the vendored card with one field (focused) and a ≥ 44 px button; a wrong secret → *wrong token or password*; the token → the `taskos_token` HttpOnly cookie is set and the page lands on `?next=` (`/#task/1`, the drawer open); Settings → **Phone access** shows the token as configured (this browser is on loopback, so it reads *this PC*; a phone reads *signed in* with a *Sign out on this device* button).
10. `/login` on the desktop (1440×900) renders the same card, centred.

**Screenshots (phone 390×844 unless noted) — saved by the test, same names the headed walk observed**

| Step | Phone |
| --- | --- |
| 2 Today, the landing tab | [story-07-phone-1-phone.png](../screenshots/story-07-phone-1-phone.png) |
| 3 quick-added task in Today | [story-07-phone-2-phone.png](../screenshots/story-07-phone-2-phone.png) |
| 4 Board carousel after the swipe (Doing) | [story-07-phone-3-phone.png](../screenshots/story-07-phone-3-phone.png) |
| 5 drawer full-screen, folder chip | [story-07-phone-4-phone.png](../screenshots/story-07-phone-4-phone.png) |
| 6 dark theme persisted (Today) | [story-07-phone-5-phone.png](../screenshots/story-07-phone-5-phone.png) |
| 7 Board carousel at 430 wide | [story-07-phone-6-phone.png](../screenshots/story-07-phone-6-phone.png) |
| 9 /login on the phone | [story-07-phone-7-phone.png](../screenshots/story-07-phone-7-phone.png) |

| Desktop | |
| --- | --- |
| 10 /login at 1440×900 | [story-07-phone-8-desktop.png](../screenshots/story-07-phone-8-desktop.png) |

**Result — 2026-08-17: verified in the browser; the real-phone leg not verified (needs the owner's phone).**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (incl. `test_auth`), the routed e2e (full tier: smoke + stories 01, 04, 05, 07 — Chromium desktop + WebKit phone).
- [x] On screen: walked headed (WebKit 390×844 touch, then 430×932; Chromium 1440×900 for the login page) on a disposable instance of this build over a freshly seeded scratch database on another port (`TASKOS_DB_PATH` → scratch; never `data/tasks.db`): observed = expected on every step above — Today first, the quick-add row landing under *No project*, the carousel snapping to *Doing* after the scroll, the drawer covering the whole screen with *Kitchen folder* as a plain chip whose tooltip is `{onedrive}/house/kitchen`, dark surviving the reload, the login card with the field focused and *wrong token or password* on a bad secret, then straight into `#task/1`. Zero page errors in the console.
- [x] HTTPS on this machine: `scripts/gen_tailscale_cert.py` provisioned `webapp/certificates/{cert,key}.pem` for this host's tailnet name (Let's Encrypt via `tailscale cert`); `--check` no-ops on the fresh leaf; `tray.bat --restart` brought the app up over HTTPS — `https://127.0.0.1:8448/api/version` `git_sha == HEAD` and `curl -sk https://<host>.ts.net:8448/healthz` → `{"ok": true}` from this machine; `GET /api/status` → `https: true`, `auth.enabled: true` (a token was generated with `scripts/gen_token.py`).
- [ ] **Not verified — needs the owner's phone.** The real-device leg of the story: open `https://<host>.ts.net:8448` in iOS Safari on the tailnet, sign in, *Add to Home Screen*, launch the installed app, walk Today → quick-add → Board swipe → drawer → folder chip. Checklist for the owner:
  1. On the PC: tray icon → **Copy URL** gives `https://<host>.ts.net:8448`; the token is in `config/config.json` → `auth.token` (`scripts\gen_token.py` printed it once — keep it in the password manager). Optionally `scripts\set_password.py <memorable>` and `tray.bat --restart`.
  2. iPhone on the tailnet (Tailscale app connected) → Safari → `https://<host>.ts.net:8448` → expect the lock icon with **no certificate warning** (Let's Encrypt leaf for the `.ts.net` name), the sign-in card → paste the token or type the password → the app opens on **Today**. Screenshot: the sign-in card; the Today tab.
  3. **Share → Add to Home Screen** → the *task-os* icon (list-checks glyph, no white frame — the maskable icon) → launch it: full-screen, no Safari chrome, the bottom pill above the home indicator, no dead band under it, no rubber-band bounce of the whole page. Screenshot: the home-screen icon; the installed app on Today.
  4. Quick-add `call the plumber today` → the row appears; swipe the Board left → the strip advances (*Todo → Doing*); tap a card → the drawer fills the screen; long-press the folder chip → the tooltip / copy fallback shows the `{…}` ref (the opener is Step 9). Screenshot: the drawer.
  5. Toggle dark; force-quit and relaunch the installed app → still dark, still signed in (no login prompt — the 90-day cookie).
  6. Android (if at hand): Chrome → **Install app** from the page menu → the same walk.
- Also verified from this machine over the **tailnet address** (a real non-loopback path — the client is the host's own Tailscale IP): `curl https://<host>.ts.net:8448/api/tasks` → `401 unauthorized`, `curl …/` → `302 → /login?next=%2F`, the same with `Authorization: Bearer <token>` → `200`; the log shows `🔒 401 GET /api/tasks from 100.x.x.x`.
- Also verified live over the tailnet URL in a desktop Chromium (a non-loopback browser: the client is the host's Tailscale IP): `/` → `302 /login?next=%2F` → the token → the cookie → the shell; Settings → Phone access reads **signed in**, `HTTPS on — Tailscale certificate`, `Access token configured`, the **Sign out on this device** button visible; `GET /api/status` → `https: true`, `auth.client: token`.
- Not verified in this step, by design: a real touch swipe on glass (the carousel was driven with a programmatic scroll); Service Worker / offline (deliberately not used in the fleet); the `--check` renewal path (a fresh leaf is 90 days out — the auto-renew leg is exercised only by the scaffold's own script tests; the first real renewal happens in ~60 days on a tray start).
