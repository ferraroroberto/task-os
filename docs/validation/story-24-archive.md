# Story 24 — the Archive tab: run the batch, read the report, fix what is wrong (#159)

**Story.** "I finished my mails, I press **Archive**, I read what went where, I fix the one or two that are wrong, and I never file a mail by hand again." The mail that needs *me* is already an Inbox task (capture, #98); everything else is filed in one run through email-archiver (#157) with the local model picking the folder (#158), and this screen is where that run is read and corrected.

This record also carries the on-screen half of **story 21** (capture into the Inbox). The e2e suite is capped at one story test per step, so when the Archive tab landed the capture walk was folded in here rather than kept as a file of its own — the two halves read the same archiver index and now share one disposable instance. Story 21's own record stays as the 2026-09-07 evidence; everything it proved that is not on screen stayed at unit level.

## Steps and expected

| # | Step | Expected |
| --- | --- | --- |
| 1 | Settings → *Capture into Inbox*, press **Check now** | the card reads `checked` and *2 flagged · 2 new*; nothing was written to the archiver's file |
| 2 | Board → open a captured task | it is an Inbox task created by `email-archiver`, carrying the `.msg` chip whose href is the per-PC `taskos://open?ref=…` link |
| 3 | Open the **Archive** tab before any run | `ready`, the ranking model named, the *first N mails* bound empty (= the whole Inbox), *Last run: never*, and an empty state saying so — never a blank pane |
| 4 | Press **Archive Inbox now** | the button disables and reads *Archiving…*; a second run is refused with 409 `archive_in_flight` — one Outlook, one run at a time |
| 5 | The run finishes | the head counts `3 mail(s) · 1 filed · 1 need you · 1 failed`, a toast says the same, and the report draws one row per mail with destination (last three path components, full path on hover), the `.msg` as an opener chip, confidence, the reason and the state |
| 6 | Look at what each row offers | `archived` → *Move to…* + *Revert*, **no Accept** (a filed mail is finished, not reviewed — the API answers 409); `needs_review` → *Accept* + *File it…*; `failed` with files → all three; `reverted` → nothing, and the row says *back in the Inbox* |
| 7 | Open the `needs_review` row's **File it…** | the candidates the run already ranked are listed with their scores (no re-plan — they are stored on the row), *Other folder…* offers the same index picker the drawer uses, and there is one optional hint field |
| 8 | Type a hint and press a candidate | the vendored confirm names the mail and the folder; on confirm the row becomes *moved by you*, its reason reads *filed here by hand from the Inbox*, and the archiver was asked to **file** it — no undo leg, because nothing was on disk |
| 9 | **Accept** the failed row | `decided_at` is stamped, no file moves, and the *Accept all N that need you* bar disappears once nothing is left |
| 10 | **Revert** the filed row | the confirm warns the file is deleted, not binned; on confirm the archiver is sent exactly that mail's files, the row becomes `reverted` and its files empty |
| 11 | Board | the Inbox header carries *N mail(s) need you* pointing at the tab — the count the **run** recorded, never a guess about what is still in Outlook |
| 12 | Command palette → *Go to Archive* | lands on the tab, like every other destination |
| 13 | Phone (390×844) | six entries in the bottom pill; the report degrades to one card per mail with the actions behind each row's *Review* |
| 14 | An install without the archiver | the head says *not configured* with the reason, the button and the bound are disabled, and the report area says the same — never a dead press |

## Proof

- **Screenshots:** [1](../screenshots/story-24-archive-1-desktop.png) (Capture card after *Check now*) · [2](../screenshots/story-24-archive-2-desktop.png) (the captured task's `.msg` chip in the drawer) · [3](../screenshots/story-24-archive-3-desktop.png) (Archive tab, nothing run yet) · [4](../screenshots/story-24-archive-4-desktop.png) (the report: filed · needs you · failed) · [5](../screenshots/story-24-archive-5-desktop.png) (filing a needs-you mail — candidates, other folder, hint typed) · [6](../screenshots/story-24-archive-6-desktop.png) (dark, after the review round: reverted · moved by you · failed-and-seen) · [7](../screenshots/story-24-archive-7-phone.png) (the report as cards) · [8](../screenshots/story-24-archive-8-phone.png) (one card's review menu, dark).
- **E2e:** `tests/e2e/test_story_24_archive.py` — one disposable instance over the synthetic archiver index (`tests/fixtures/emails_fixture.py`) **and** the fake archiver checkout (`tests/fixtures/archiver_fake.build_fake_archiver`: a real `main_batch.py` with canned JSON answers, so the argv, the temp decisions file, the UTF-8 decode, the exit codes and the timeout all run for real, with no Outlook anywhere). `archive.enabled` is true only in that instance's temp config; `tests/test_archive.py::test_the_sample_config_never_arms_the_real_archiver` keeps the committed sample off, so a fresh clone, a worktree and the gate itself can never drive this machine's Outlook.
- **Unit/API:** `tests/test_archive.py` — the run state machine, the two-layer folder decision, the correction memory, the four classified failures, and (new for #159) `test_move_files_a_needs_review_mail_that_was_never_archived` and `test_move_refuses_a_reverted_mail_and_names_why`. `tests/test_capture.py` + `tests/test_api.py` keep story 21's off-screen half: the re-run that creates nothing, the un-flagged mail whose task stays, the folded `.msg` ref as `external_id`, the WhatsApp replay, and the *not configured* reason a pre-flag archiver produces.

## One backend rule this step had to add

`POST /api/archive/items/{id}/move` refused a `needs_review` mail before this step: it always reverted first, and `_require_revertible` rejects a row with nothing on disk. But *filing the mail the ranking would not decide* is the commonest thing anyone does on this screen, so the acceptance criterion could not be met from the UI alone. `move` now skips the undo leg for a row that was never filed (`_require_movable`), the "already filed in that folder" guard applies only to a row that really is filed there — otherwise accepting the model's own low-confidence pick would have been refused — and the recorded reason distinguishes *filed here by hand from the Inbox* from *moved here by hand from ‹folder›*, so the log never claims a filing that did not happen.

## Live walk — the real archiver, a real Outlook (2026-09-09)

Walked in visible Chrome on the live `:8448` instance (build `1d0e1fd`) against the real email-archiver checkout and a real Outlook, bounded to **one mail**.

- **Before.** The tab opened on the previous run (`reverted`, *back in the Inbox* in place of any action), the head reading *ready · model `claude_haiku` · batches of 8 · 20 corrections remembered*.
- **Run.** *first `1` mails* → *Archive Inbox now*. The button disabled and read *Archiving…*, the progress line showed the counters at zero and the report area said *The run has started — mails appear as they are decided*. It finished on its own in about 25 s, one mail `filed` at **95%** confidence with the model's own one-line reason, and the run recorded *model agreed with the suggester on 0%* — the model picked candidate #2, not the archiver's top one.
- **A second run while that one was going** answered `409 archive_in_flight` with its own sentence.
- **Accept was deliberately not offered** on that row, and the API agrees: `POST …/accept` on it answers `409 archive_bad_state` — *"archive item 6 is archived, which needs no review"*. A filed mail is finished, not reviewed; the screen draws no control the API would refuse.
- **Move with a hint.** *Move to…* opened a full-width panel under the row listing the candidates the run had ranked and discarded, each with its score, the folder the mail was actually filed in correctly absent. A hint was typed and the discarded top candidate pressed; the confirm named the mail, the destination and the hint, and after it the row read *moved by you*, with the new `.msg` chip, a blank confidence (a human pick has none) and the reason *moved here by hand from ‹the previous folder›*. An `archive_corrections` row was written carrying the hint.
- **Revert.** *Revert* on the same row, with its warning that the file is deleted rather than binned. The row became `reverted`, its files empty, the actions cell read *back in the Inbox*, and **both** `.msg` files — the one the run wrote and the one the move wrote — were gone from disk.
- **Not walked, deliberately:** archiving a whole Inbox in one press, and any run touching more than one real mail. The Board's *N mail(s) need you* link could not be seen live either, because this run left nothing undecided; it is covered by the e2e story. See the owner's checklist in `docs/validation.md`.

The exact counts, folder names and subjects of the live walk are **not** recorded here: this repo is public and every folder and subject in a real run is personal. What is on screen above is the synthetic fixture only.

## Result

Verified: e2e on the disposable instance (desktop light + dark and phone light + dark), unit and API, plus the live headed walk above.

## Deliberate limits

- No scheduling, no tray entry, no Stream Deck button — the run is a press, on purpose, until the manual flow is trusted (out of scope in #159).
- The tab never edits a file name or the archive tree: the archiver owns both.
- *N mail(s) need you* on the Board reports what the **last run** recorded. How many mails are sitting in Outlook right now is not knowable without running a plan, and the screen does not pretend otherwise.
- A run's counters are frozen when it closes, so reviewing rows afterwards does not rewrite them — the run is a record of what happened, not a live tally.
