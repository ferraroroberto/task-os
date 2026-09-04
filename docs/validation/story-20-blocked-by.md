# Story 20 — Blocked-by dependencies (#100)

**Story.** "Order tiles" can't happen until "Confirm measurements" is done. Set a **Blocked by** dependency in the drawer and the blocked task drops out of Board / Today / plan candidates wearing a lock — the same working-view rule `starts` (#87) already had, applied to a second graph. The Tree, search and the drawer keep showing it, with the lock and "blocked by N" in place of any sleeping marker (blocked is the harder gate, so it wins when a task is both). The status multi-select's `blocked` pseudo-filter is the one visible way to list exactly the locked tasks, same shape as `deferred`. A cycle or a self-block is refused everywhere it could be attempted — the drawer's picker, the API, the CLI, a mirror file edit — recorded as a rejected `mirror_events` row when it comes from a file, never a comment. Deleting a blocker frees its dependents automatically, with an activity row on the survivor explaining why.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Seed: "Release v0.2" blocked by "Write sensor driver" → Board | The row is absent from every column (hidden by default, like a deferred task) |
| 2 | Tree | "Release v0.2" is there, wearing a lock glyph + "blocked by 1" instead of any starts marker |
| 3 | Open its drawer | The "Blocked by" section lists "Write sensor driver" as a removable row with its status pill |
| 4 | Filter card → status multi-select → `blocked` | The Board narrows to exactly "Release v0.2" |
| 5 | Two fresh tasks, block B on A via the drawer picker, then try to block A back on B | The first add succeeds; the second is refused — a toast naming the cycle, nothing applied, `blocked_by` stays empty on B |
| 6 | Remove the real edge (the trash icon on the blocker row) | The section reads "Not blocked by anything." again, `blocked` flips back to `false` |
| 7 | CLI: `tasks block N --on M`, `tasks unblock N M`, `tasks ls --blocked` | Same cycle/self-block guard (exit 1, `code: "cycle"` under `--json`); `ls --blocked` lists exactly the locked tasks; `show` names the blocker |
| 8 | API: `POST/GET/DELETE /api/tasks/{id}/blockers`, `?status=blocked` | 201/200/404 as expected; a self-block or cycle is 409 `cycle`; the pseudo-filter matches the CLI/UI |
| 9 | Mirror | `blocked_by: [ids]` exports as an inline list, imports edge-by-edge through the same repo calls, a cyclic file edit is rejected and recorded as a `mirror_events` row, never a comment |
| 10 | Delete a blocker task | Its edges cascade; a still-alive dependent gets a `blocked_by` old→None activity row explaining the unblock |

## Proof

- Screenshots: [1](../screenshots/story-20-blocked-by-1-desktop.png) (Board without the locked task) · [2](../screenshots/story-20-blocked-by-2-desktop.png) (Tree, lock + count) · [3](../screenshots/story-20-blocked-by-3-desktop.png) (drawer's Blocked by section) · [4](../screenshots/story-20-blocked-by-4-desktop.png) (the `blocked` filter, one row) · [5](../screenshots/story-20-blocked-by-5-desktop.png) (drawer, dark, the picker mid-cycle-attempt).
- E2e: `tests/e2e/test_story_20_blocked_by.py` — desktop only (Chromium, light + one dark shot); no separate phone leg, since the feature rides the already phone-verified shared row (`rows.js`) and filter-card multi-select (both proven on the phone in story 04).
- Unit: `tests/test_repo.py` (`test_seeded_blocked_pair`, `test_add_blocker_refuses_self_and_cycle`, `test_add_and_remove_blocker_logs_both_sides_and_is_idempotent`, `test_a_closed_blocker_does_not_block`, `test_delete_a_blocker_logs_unblock_on_the_survivor`) · `tests/test_mirror.py::test_blocked_by_round_trips_and_rejects_a_cycle` · `tests/test_api.py::test_blockers_add_remove_cycle_and_the_blocked_filter` · `tests/test_cli.py::test_block_unblock_and_ls_blocked_over_both_backends` · `tests/test_schema.py` (the v11 migration, `task_blocks` in `EXPECTED_TABLES`).

## Result

verified (e2e walk on the seeded instance, screenshots read back, both themes represented · full unit suite green · gate — byte-compile, ruff, 410 unit tests, 15 e2e tests — green twice in a row). **Not separately walked**: a live headed browser session against a running instance outside the automated Playwright suite, and the real phone (no phone-specific e2e leg — see the proof note above for why). Date: 2026-09-04.

**Deliberate limits (from the issue):** edges only, no ordering/critical-path view, no auto-surfaced "next action" beyond the hide itself, no cross-project rollups, no unblock notification.
