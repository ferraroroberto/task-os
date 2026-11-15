# Story 27 — A teammate comments (team mode)

**Issue:** #13 (Step 12/13). Numbered 27 because Step stories take the index's next free number (see `docs/validation.md`); the issue text predates that rule and says `test_story_12_team.py`.

**Tests:** `tests/e2e/test_story_27_team.py::test_teammate_signs_in_picks_a_name_and_comments` (two browser contexts, one seeded disposable instance with team mode on — synthetic people, synthetic token and team password) · `tests/test_auth.py` team section (9): team mode **off** leaves the Step 7 model unchanged (a team password in the file and team cookies in the jar are ignored, the token login answers exactly as before, the name cookie never becomes the author, `/api/team/name` is 409) · the team password signs a non-loopback client in with a `taskos_team` cookie that is never the owner's token (same access while valid), the gate passes it, every page redirects to `/login?step=name` until a name from `team.people` is picked (422 for any other), and the picked name is the comment author and the activity actor (an explicit `actor` / `author` still wins) · sign-out clears all three cookies · a new team password or a rotated token kills the team cookie · team mode with no token stays closed (503, no team cookie can match) and with no team password accepts no team sign-in · loopback is never asked for a name but can pick one, and a name dropped from the config is ignored · `Secure` on both cookies over HTTPS · avatars by slug from `data/avatars/`, gated, 404 without a file · the sample ships team off with no password · `scripts/set_team_password.py` (no token → refused, too short / mismatch → refused, success keeps `team.enabled` + `people`, `--clear`, the password never printed).

The e2e budget: adding this file would have taken the suite to 17 collected tests, so story 05's phone leg was folded into its desktop test (`test_desktop_board_day` now runs both walks — same steps, same order, same shots). The count stays at 16.

**Steps → expected (the acceptance story)**

1. The owner sets `team.enabled = true` and `team.people` in `config/config.json`, runs `scripts/gen_token.py` (if there is no token yet) and `scripts/set_team_password.py` (typed twice, not echoed), then `tray.bat --restart`.
2. A second person on the same private network opens the URL → the sign-in card → types the **team password** → the *Who are you?* card lists the people.
3. They pick their name → the app opens where they were headed; any page they open before picking sends them back to that card.
4. They open a task, comment with a link and a folder ref → the comment row shows **their name** above the text, with a web chip and a folder chip.
5. They click the folder chip → their own PC's opener (story 09, installed on their machine) opens their synced copy of that folder.
6. The owner opens the same task → the comment is under the teammate's name; the owner's reply is under the owner's.
7. Settings → *Phone access* on the teammate's browser reads **team member** · *Team: you are <name> · change name*; *Sign out on this device* clears the sign-in and the name.
8. The owner opens Settings → *This install* → **Your name**: the row reads *not set* and the field's placeholder the fallback (*Alex Chen*, the first team member). They type a name and press *Save name* → the row reads the new name at once, the sheet says *recorded as …*, and the next comment they add is under that name. Clearing the field and saving restores the fallback for the next comment. The name is written to `your_name` in the config file the app loaded; no restart.

**Screenshots** (synthetic seed only)

| # | Shot | What it shows |
| --- | --- | --- |
| 1 | [story-27-team-1-desktop](../screenshots/story-27-team-1-desktop.png) | *Who are you?* right after the team password — three people, initials (no avatar files) |
| 2 | [story-27-team-2-desktop](../screenshots/story-27-team-2-desktop.png) | the teammate's comment on *Get three quotes*, signed **Sam Rivera**, with the `example.com` web chip and the `plans` folder chip |
| 3 | [story-27-team-3-desktop](../screenshots/story-27-team-3-desktop.png) | the owner's browser (dark): Sam's comment under Sam's name, the owner's reply under the name they saved in *Your name* (**Ada Example**), the activity row `priority none → high · Sam Rivera` |
| 4 | [story-27-team-4-phone](../screenshots/story-27-team-4-phone.png) | *Who are you?* at 390 px, dark — full-width 52 px rows |
| 5 | [story-27-team-5-desktop](../screenshots/story-27-team-5-desktop.png) | Settings → *Your name* (dark): the sheet beside the list after *Save name*, the row reading the saved name |
| 6 | [story-27-team-6-phone](../screenshots/story-27-team-6-phone.png) | the same sheet at 390 px, light — full-width field and button, both ≥ 44 px targets |

**Result**

| Leg | Result |
| --- | --- |
| Unit — `tests/test_auth.py` (20, 9 of them team mode) | verified 2026-09-13 |
| E2e — `test_story_27_team.py`, two contexts against a loopback disposable instance: team password → `taskos_team` (HttpOnly, no `taskos_token`) → pick *Sam Rivera* → `taskos_name` (HttpOnly) → deep link restored → comment signed Sam with both chips → the folder chip's click is handed to `taskos://open?ref=…` (intercepted, as in story 09) → activity actor Sam → Settings row; owner context → Sam's comment, reply signed Alex Chen; phone card ≥ 44 px targets, no horizontal overflow | verified 2026-09-13 |
| Headed two-browser walk on this PC — a disposable instance (synthetic seed, synthetic secrets) bound to this PC's **LAN address**, so both Chromium windows were genuine non-loopback clients: `/` → `/login?next=%2F` · team password → pick card, cookie jar `taskos_team` only · a second tab before picking → `/login?step=name&next=%2F%3Fproject%3D1` · pick Sam Rivera → `/`, `auth.client = team` · comment row author *Sam Rivera*, folder chip `taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen%2Fplans` · owner window signed in with the token → sees Sam's comment, reply signed *Alex Chen* · teammate reload → owner's reply under *Alex Chen* · Settings *team member* · *you are Sam Rivera · change name* · sign out → `/login`, `/api/tasks` 401, no cookies left. Screenshots inspected in-session, not committed | verified 2026-09-13 |
| Folder chip opening the teammate's **own** synced copy through the opener on **their** PC (step 5) | **not verified** — the click hands off to `taskos://` (proved above); the opener itself is story 09's, and a second PC with it installed was not available |
| **A second real person on a second PC, over the private network, steps 1–7** | **not verified** — deferred until a second person is available (issue #13) |
| E2e — the same test's owner leg and a phone leg walk *Your name* (2026-11-15): fallback shown → *Ada Example* saved → the next comment is signed *Ada Example* → cleared → the next comment is signed *Alex Chen* again; phone: ≥ 44 px field and button, no horizontal overflow | verified 2026-11-15 |
| Unit — `tests/tasks/test_install_author.py`: the save signs the next comment and activity and survives a reload of the file (other keys untouched); clearing restores the fallback; the mirror's file-comment author follows live; an over-long or control-character name is 422 and writes nothing; the sample config is never written (409); a non-loopback client with no token is refused | verified 2026-11-15 |
| Real-browser walk on a scratch instance (synthetic seed, a real server process): the sheet opened from `#settings/yourname`, the placeholder read *Alex Chen*, *Walker Example* typed and submitted with Enter → the status line and row updated, `your_name` was in the config file, a comment posted without an actor was signed *Walker Example*; cleared → comment signed *Alex Chen*, `your_name` back to blank | verified 2026-11-15 |
