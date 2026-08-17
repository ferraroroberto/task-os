# Story 01 — Open the app

**Issue:** #2 (Step 1/13). **Test:** `tests/e2e/test_story_01_open.py` (3 tests: API leg, desktop leg, phone leg).

**Steps → expected**

1. Run `tray.bat` → a tray icon appears; the webapp comes up on `http://127.0.0.1:8448` (`/healthz` 200).
2. Open the URL (left-click the tray icon) → the shell renders: top nav `Board · Table · Tree · Today · Search · Settings` (Board active), the `task-os` header card, the empty state **"Add your first task"** in every task pane, and a footer `Build: <sha> · <time>` where `<sha>` equals `/api/version`'s `git_sha`.
3. Click the theme toggle → the page flips to dark; reload → still dark (persisted under `task-os.theme`); click again → light.
4. Switch to another tab and reload → the tab persists.
5. On a 390-wide phone (WebKit emulation) → the nav is the floating bottom pill, all targets ≥ 44 px, no horizontal overflow; the same toggle flips and persists.

**Screenshots (desktop 1440×900, phone 390×844)**

| | Light | Dark |
| --- | --- | --- |
| Desktop | [story-01-open-1-desktop.png](../screenshots/story-01-open-1-desktop.png) | [story-01-open-2-desktop.png](../screenshots/story-01-open-2-desktop.png) |
| Phone | [story-01-open-1-phone.png](../screenshots/story-01-open-1-phone.png) | [story-01-open-2-phone.png](../screenshots/story-01-open-2-phone.png) |

**Result — 2026-08-17: verified.**

- [x] Automated: `verify-before-ship.ps1` green (byte-compile, ruff, 11 unit tests, e2e full tier — smoke + the 3 story tests, Chromium desktop + WebKit phone).
- [x] On screen: walked headed on the live tray build at `:8448` (desktop 1440 wide, then phone 390 wide) — the four shots above are the proof; the same run showed the tray icon, `/api/version` `git_sha == HEAD`.
- Not verified in this step: PWA install on a real iPhone and HTTPS (Step 7); anything beyond the empty shell (no tasks exist yet — Step 2 brings the schema, Step 4 the first task).
