# AI conversation links

Paste the URL of an AI conversation into a task's links — Claude Code / claude.ai, ChatGPT, Gemini, GitHub Copilot, Microsoft Copilot are all recognised and stored as one kind (`ai`), no per-provider split — and the task wears a **bot chip** on the Board and Today rows, same as the folder chip. A Claude Code session page shows the full transcript even after the local session ended (archived sessions stay readable), so the link never rots.

The recognition is the server's (`tasks_repo.infer_link_kind`), so an agent in a conversation gets the same result from the terminal: `tasks add "…" --link <session-url> --folder <ref>` creates the task already connected, and `tasks link N <session-url>` attaches the conversation to an existing one.

- **Phone (coarse pointer):** tapping the chip opens the conversation in a new tab — there is no CLI to resume into.
- **Desktop:** clicking the chip opens a small popover — **Open conversation** (the usual choice, new tab) and, for a `claude.ai/code/session_…` URL, **Resume in CLI on this PC** (`taskos://resume?session=…`). The same per-PC opener that opens folders searches `%USERPROFILE%\.claude\projects` for the transcript carrying that session id, and reopens it in a terminal (`wt` when installed) running `claude --resume <local-session-uuid>` **in the repo the session ran in** — that terminal is the one deliberate exception to the opener's "no window" rule, since it's the feature. A session this PC never saw falls back to opening the web page, with a popup notice. The pure-`cmd` fallback registration cannot search transcripts — it says so instead of degrading silently.

Where to get the URL: every Claude Code commit carries a `Claude-Session: https://claude.ai/code/session_…` trailer, the session list at claude.ai/code shows it, or ask the session itself for its link. List summaries carry `ai_url` + `ai_label` (the first `ai` link) so rows never scan the links table client-side.

Folder links and the folder index that backs the drawer's folder picker are documented in [Folders that open on any PC](folders.md#folders-that-open-on-any-pc).
