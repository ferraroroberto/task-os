# Story 23 — Triage the Inbox with staged AI suggestions (#95)

**Story.** Open the Board after captured work has accumulated in Inbox and press **Triage** once. Every Inbox row gains one quiet proposal — project, priority, due and person — but the task itself stays exactly where it was. Review the proposals one at a time: ✓ applies that row and moves it to Todo; × discards it. The model never gets an accept-all button and never writes a task by itself.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Open Board with Inbox tasks and a reachable configured local hub | **Triage** is enabled in the Inbox header; the phone shows the same action above the active Inbox column |
| 2 | Press **Triage** | The action reads **Triaging…** and is disabled while exactly one bounded request is in flight |
| 3 | Wait for the answer | Every requested Inbox task has one staged strip naming project/top level, priority, due/none and person/unassigned; its reason is available as the strip tooltip; no task field or status changed |
| 4 | Accept one proposal with ✓ | Only that suggestion is applied; the task moves from Inbox to **Todo** and the activity rows for every changed field name actor `ai` |
| 5 | Reject another with × | Only that suggestion disappears and its task is untouched in Inbox |
| 6 | Open Settings → *AI Inbox triage* | The card says `on` and `reachable`, names the configured model and explains that suggestions stay staged |
| 7 | Disable AI or stop the hub | The Board action remains visible as **Triage off** or **AI unavailable** with its reason; Settings and `/api/status` report the same state |
| 8 | Run `tasks triage` | Human output walks the same staged suggestions with `y/n/q`; `--json` returns the staged API shape without prompting or accepting anything |
| 9 | Make the model answer with malformed JSON, missing/extra ids, an unknown id, invalid date/priority/person/project or a cycle | The whole answer is `ai_invalid_response`; **nothing** is staged or applied, and an already-pending batch is not erased |

## Proof

- **Screenshots:** [1](../screenshots/story-23-ai-triage-1-desktop.png) (four staged proposals on the desktop Board) · [2](../screenshots/story-23-ai-triage-2-desktop.png) (one accepted task has moved to Todo while the other proposals remain) · [3](../screenshots/story-23-ai-triage-3-phone.png) (dark 390×844 Inbox with the full-width action and touch-sized ✓ / × controls).
- **E2e:** `tests/e2e/test_story_23_ai_triage.py` — a disposable seeded instance points at `tests/fixtures/anthropic_fake.FakeAnthropic`. The fake reads the actual compact context and returns one suggestion per supplied Inbox id; the story drives the shipped Board action, waits for the staged strips, accepts one, verifies the task in Todo plus the `ai` activity actor through the API, checks the Settings status, and repeats the staged view in a 390-wide touch context.
- **Unit/API/CLI:** `tests/test_ai.py` covers context assembly; staging without task writes; pending replacement; whole-response rejection for bad ids, types, top-level shape, date and parent cycle; all-field acceptance + Todo + actor `ai`; rejection without task writes; disabled versus unreachable status; a real Anthropic SDK request against the fake server; and the HTTP routes. `tests/test_cli.py` covers both human review and non-interactive JSON output.

## Live walk — real local hub and model (2026-09-08)

A disposable instance over the public synthetic seed was configured for the real hub at `127.0.0.1:8000` and model alias `claude_haiku`, then walked in visible Chrome. No real task database was opened and no private task text reached the model.

- Pressing **Triage** changed the action to *Triaging…* for one request. The hub answered `200` in **23.2 s**: `1248` context characters → `792` output characters, and all four proposals appeared together.
- The returned proposals were plausible and specific to the supplied fixture: *Compare phone plans* → **Family admin · medium · 2026-09-20 · unassigned**; *Look into a standing desk* → **Home renovation · low · no due · unassigned**; *Try the new bakery* → **top level · low · no due · unassigned**; *Reading list* → **Side project: garden-bot · medium · no due · unassigned**.
- Before acceptance all four rows still read `inbox`. Accepting *Compare phone plans* dropped Inbox from 4 → 3 and raised Todo from 26 → 27. Its drawer showed status `todo`, parent **Family admin**, priority **medium**, due **2026-09-20**, and separate parent/priority/status activity rows all stamped `ai · 8 Sep 09:00`.
- Settings showed *AI Inbox triage — on*, then, expanded, *Local AI: reachable · checked 9/8/26, 9:00 AM* and model `claude_haiku`.

## Result

Verified on the synthetic story fixture in desktop light and phone dark layouts, and re-walked against the real local hub/model in visible dark-mode Chrome. The real-data install was deliberately not used because Inbox task text is model input and public validation artifacts must contain synthetic data only.

## Deliberate limits

Only Inbox classification ships here. There is no automatic application, accept-all, free-form task editing, title/description rewriting, task creation, chat surface or background triage. One run handles at most 50 Inbox tasks and includes at most 200 open project nodes; task descriptions and model reasons are bounded before storage/logging.
