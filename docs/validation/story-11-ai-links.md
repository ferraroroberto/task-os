# Story 11 — the AI conversation on the task (issue #77)

> I keep a link to the AI conversation behind a task — Claude Code, ChatGPT, Gemini, Copilot, all the same — and the task wears a bot chip. On my phone I tap it and read the conversation. At my PC I click it and choose: open it on the web (the usual), or resume the session in the CLI, in the repo it ran in.

Not a numbered build step — a feature issue validated story-style. The automated walk lives **inside `tests/e2e/test_story_09_folders.py`** (same surface: chips that open things through the per-PC opener; the suite stays under 15 tests), sections "issue #77".

## Steps and expected

| # | Step | Expected | Shot |
| --- | --- | --- | --- |
| 1 | Seeded Table, `status:doing` — the garden-bot task carries an `ai` link | The row's chips cell shows the **bot chip** (`drift-fix session`), href = the conversation URL | [1-desktop](../screenshots/story-11-ai-links-1-desktop.png) |
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
