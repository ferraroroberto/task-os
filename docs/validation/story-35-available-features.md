# Story 35 — Available features (#712)

**Issue:** #712. **Tests:** `tests/features/test_features.py` (unit and API, one test per block) and the `_available_features` leg inside `tests/e2e/test_story_07_phone.py` (WebKit device emulation, 390×844, light then dark).

**User story:** on another computer I switch off the parts of the app whose dependency is not there, once, in Settings. The code is the same; only that machine's config differs.

**Steps → expected**

1. Settings → *Available features* lists six blocks (Time tracker, Calendar lane, Issue sync, Email and folders, Local AI, Mirror and backups), each with a switch and one line on what it covers. Every switch is on on a fresh install. A block that is on but has no dependency here says so in the attention tone (*On, unavailable here: …*).
2. Switch *Time tracker* off → the switch flips, `html[data-features-off="time"]`, the Time tab leaves the pill (three tabs remain), the *Time categories* row leaves Settings, `GET /api/time/meta` answers `409 feature_off`, and `GET /api/board` still answers 200.
3. Reload → the page is served with `data-features-off="time"` already set, so nothing flashes; the state is in the machine's `config/config.json` (`features: {time: false}`), not in the repository.
4. Open it in dark → the row reads *Off on this machine*.
5. Switch it on → the tab and the route are back with no restart; the `features` key is removed from the config.

Per block, the unit tests prove the same three effects: routes answer `409 feature_off`; background work stops and restarts (the issue poller, the flagged-mail poller, the mirror watcher and the backup scheduler); the `/api/status` section and the search group read *off* with one reason, and nothing reaches the service behind it (no calendar fetch, no folder-explorer request).

**Screenshots (phone 390×844)**

| Step | Phone |
| --- | --- |
| 1 the group, every block on (light) | [story-07-phone-12-phone.png](../screenshots/story-07-phone-12-phone.png) |
| 4 Time off, the tab and its row gone (dark) | [story-07-phone-13-phone.png](../screenshots/story-07-phone-13-phone.png) |

**Result:** verified in the browser (e2e phone, light and dark, scripted walk) and by unit tests. **Not verified:** a headed walk by hand, a real calendar feed, real folder-explorer or a real hub going away under a live switch; the Today lane, the quick-add mic and the Board's triage button are hidden by the same `data-feature` rule and are covered by the unit tests and the CSS-rule test, not by a screenshot. **Date:** 2026-11-16.
