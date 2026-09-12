# Story 11 — the AI conversation on the task (issue #77)

> I keep a link to the AI conversation behind a task — Claude Code, ChatGPT, Gemini, Copilot, all the same — and the task wears a bot chip. On my phone I tap it and read the conversation. At my PC I click it and choose: open it on the web (the usual), or resume the session in the CLI, in the repo it ran in.

Not a numbered build step — a feature issue validated story-style. The automated walk lives **inside `tests/e2e/test_story_09_folders.py`** (same surface: chips that open things through the per-PC opener; the suite stays under 15 tests), sections "issue #77".

## Steps and expected

| # | Step | Expected | Shot |
| --- | --- | --- | --- |
| 1 | Seeded Table, `status:todo` — the garden-bot task carries an `ai` link | The row's chips cell shows the **bot chip** (`drift-fix session`), href = the conversation URL | [1-desktop](../screenshots/story-11-ai-links-1-desktop.png) |
| 2 | Click the chip (fine pointer) | No navigation, no drawer — the popover: **Open conversation** (new tab) + **Resume in CLI on this PC** (`taskos://resume?session=…`, shown because the URL is a `claude.ai/code/session_…`) | [2-desktop](../screenshots/story-11-ai-links-2-desktop.png) |
| 3 | Click *Resume in CLI* | The `taskos://` URL is handed to the OS (intercepted in the test; live hand-off proven below); popover closes | — |
| 4 | Drawer → Links; paste `https://chatgpt.com/c/…` with no kind | The row wears the bot chip too; the API stored `kind: "ai"` (inferred); the delete button is borderless at the chip's height with the 44px hit rect on `::before` | [3-desktop](../screenshots/story-11-ai-links-3-desktop.png) |
| 5 | Phone (390 touch), drawer → tap the bot chip | The conversation opens directly in a new tab (stubbed in the test) — no popover, no resume on a phone | [4-phone](../screenshots/story-11-ai-links-4-phone.png) |

Unit legs: `tests/test_schema.py::test_v5_rebuild_keeps_links_and_accepts_ai_kind` (v4→v5 rebuild keeps rows + ids, accepts `ai`, rejects unknown), `tests/test_api.py::test_links_issue_and_people` (ai kind + `ai_url`/`ai_label` on list summaries), `tests/test_opener.py::test_resume_*` (the launcher maps a web session id → local transcript uuid + its repo, dry-run, real `powershell.exe`; unknown id → `resume-web:` fallback; the `.cmd` fallback registration refuses visibly).

## Real walk (this PC, 2026-08-26)

- Opener resume against the **real transcript store** (`%USERPROFILE%\.claude\projects`, dry-run): `opener.ps1 -Url "taskos://resume?session=<a real session id>"` printed `resume: <that session's local uuid> in <the repo it ran in>` — the mapping holds on real data, not just the fixture. This walk caught a real bug the fixture missed: a newer transcript that merely *mentioned* the id (a grep result quoted in another conversation) shadowed the owner — fixed by matching the transcript's own session-url marker first, bare id only as fallback, with a shadow-decoy unit test pinned.
- A claude.ai/code session URL of a **finished** session renders the full transcript read-only ("This session is archived") — verified in Chrome; the link stays useful after the CLI session ends.
- Live instance walk (Chrome, real data on a **copy** of the live DB, this build serving): the bot chip on the Board card and in the drawer, the open/resume popover, *Open conversation* → the real session transcript on claude.ai/code. A comment containing an AI URL renders the bot chip through `linkify` too.
- **Real terminal spawn**: the opener was reinstalled from this build (`install_opener.py`, launcher mode) and a non-dry `taskos://resume?session=<real id>` opened `wt -d <that session's repo>` running `claude --resume <its local uuid>` — process chain observed (`WindowsTerminal.exe` → `powershell.exe` → `claude.exe --resume …`), then the test terminal was closed.
- Real phone tap: **owner's checklist** (validated on the issue before merge).

Result: **verified** (e2e + unit + real-data dry-run + live-instance walk + real terminal spawn) · real phone = owner's checklist. Date: 2026-08-26.

## Correction — the terminal spawn was never one tab (2026-09-12, #227)

The 2026-08-26 spawn walk above read the *process chain* and stopped there, so it recorded a pass over a launch that was broken three ways at once. `;` is Windows Terminal's own new-tab delimiter and it splits on one **before** the quoting of the argument is considered, so the `;`-separated `-Command` arrived as three tabs: a bare prompt carrying only the first echo, a tab that tried to run `Write-Host` as an executable (`0x80070002`), and the real `claude` — which, being the third chunk, never saw `-d` and so resumed in `system32` rather than the repo. Separately the transcript scan sorted *after* it filtered, which blocks the pipeline: `Select-Object -First 1` could not short-circuit the filter, so every transcript on the PC was read on every resume (~170 s, and twice over on a miss). The lesson for this record: a process chain is not a tab count, and "the feature launched" is not "the feature worked".

Re-walked on this PC against the #227 build, non-dry, real transcript store (12,431 transcripts / 4.5 GB):

| # | Action | Observed |
|---|---|---|
| 1 | Dry run, `taskos://resume?session=<a real session id>` | `resume: <that session's local uuid> in <the repo it ran in>` in **1.96 s** (was ~170 s), and the new `resume-exec:` line showing `wt -d <that repo> powershell -NoProfile -NoExit -EncodedCommand <base64>` — no bare `;` anywhere in it |
| 2 | Non-dry launch — children of `WindowsTerminal.exe` | **one** shell child (`powershell.exe … -EncodedCommand …`) beside wt's own `OpenConsole.exe`; pre-fix this was three |
| 3 | The tab itself (window captured and read in session, not committed) | one tab in the tab bar; the `in <that repo> — the first paint of a long session can take a minute...` notice printed *inside* it; Claude Code resumed on that repo and its statusline showed that repo and its branch — **not** `system32`; no `0x80070002` tab |
| 4 | Marker precedence on real data | the newest transcript on the PC (this very session's) merely *mentions* the id; the owning transcript still won |

The probe terminal was closed afterwards. The worst case — no owner anywhere in the store — is now a single full traversal, measured at 9–25 s on this corpus depending on page-cache state, against the ~5–6 minutes two traversals used to cost.

Result: **verified** (one-tab spawn + repo cwd + both echoes + timing, all observed). Date: 2026-09-12.
