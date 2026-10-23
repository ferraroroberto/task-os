# Inbox

## Inbox is for what arrives

A task you add by hand starts in **To Do**, not Inbox — in the quick-add dialog, from `POST /api/tasks` with no `status`, and from `tasks add`. Inbox is the arrivals tray for things that came in *on their own* (see [Capture into the Inbox](#capture-into-the-inbox)): a flagged email, a marked WhatsApp message — things you have not looked at yet. Something you typed or spoke has already been triaged by the act of writing it, so sending it to Inbox would mean moving every manual task twice.

One name behind all of it — `src/schema.py`'s `DEFAULT_STATUS` — so the terminal and the UI cannot disagree about what "no status given" means. Capture names `inbox` for itself rather than inheriting that default, which is what keeps the tray filling with what it is for. To file something for later triage by hand, say so: the quick-add **Status** select, or `tasks add "…" --status inbox`.

## AI Inbox triage

The Board's Status mode has one **Triage Inbox** action on its mode line, shown while the Inbox holds tasks. It sends the current Inbox tasks, their descriptions, the open project tree and people list to the configured [local-llm-hub](https://github.com/ferraroroberto/local-llm-hub) in one request. The model proposes a project (or top level), priority, due date (or none) and person (or unassigned) for every task. Nothing on a task changes yet: each proposal is stored as a pending `ai_suggestions` row and appears directly under its task with an individual ✓ / ×. Accepting applies all four proposed fields with activity actor `ai` and moves that task to **Todo**; rejecting discards only that proposal. There is deliberately no accept-all and no automatic application.

The response is an all-or-nothing contract. It must be JSON with exactly one result for every requested task and no others; every task, project and person id must exist in the supplied context, priority and date must be valid, and a proposed parent must not form a cycle. Any malformed or incomplete answer stages **nothing**. Re-running Triage replaces the pending batch only after the new answer has passed the whole validation, so a bad retry does not erase suggestions already waiting for review.

`tasks triage` is the same flow in a terminal: it prints each staged proposal and asks `y/n/q`; `--json` stages and returns the API shape without prompting, so scripts never accept work accidentally. One run is capped at 50 Inbox tasks and descriptions are truncated before they reach the model. The hub is called through the Anthropic-compatible `/v1/messages` interface using `ai.model`; there are no automatic retries, and a second run while one is in flight is refused. The Board action, Settings → *AI Inbox triage*, `/api/status` and CLI status all spell out **off** or **AI unavailable** when the feature is disabled or the local hub cannot be reached.

## Capture into the Inbox

Search is *pull* — you go looking. Capture is *push*: something you already marked elsewhere lands in Inbox on its own, so nothing depends on remembering it. Two channels, both idempotent, both **one-way**.

**Flagged emails.** `src/email_capture.py` polls the archiver's index — the same `search.email_db` file the emails adapter searches, opened the same way (`file:…?mode=ro`, a fresh connection per query, never a write, never a migration: the archiver owns that file). Every message carrying an Outlook **follow-up flag** becomes an Inbox task: title = the subject, description = `From email: sender · date` + the flag's own text + the preview, plus a `links(kind=email)` row holding the `.msg` ref — so the existing [opener chip](folders.md#folders-that-open-on-any-pc) opens the mail with no new UI. `created_by` is `email-archiver`, so the activity row says which channel brought it in.

The flag is something the **archiver** records while scanning, in two columns this repo only ever reads:

| Column | Source | Meaning |
| --- | --- | --- |
| `flag_status` | MAPI `PidTagFlagStatus` (`0x1090`) | `0`/absent = none · `1` = complete · `2` = flagged for follow-up |
| `flag_request` | `PidLidFlagRequest` | the flag's text ("Follow up"), nullable |

> **Partially shipped.** `email-archiver` records `flag_status`, so a current install captures flagged mail into Inbox. `flag_request` (the flag's own text) is not recorded yet, so the captured task's description falls back to sender · date · preview with no `Flag:` line — the poller starts carrying it the moment the archiver ships that column, with no change here. The gesture it is built for is *flag in Outlook, then archive as usual*: the index covers archived mail, so a flagged message you never archive is never seen.

**WhatsApp messages.** whatsapp-radar owns its own data and its own UX; when you mark a message it POSTs `/api/tasks` with the message id as `external_id` and the bearer token. task-os just receives.

**Both dedupe on `external_id`**, and that is the whole contract: `POST /api/tasks` carrying one is idempotent — the first call creates (**201**), every replay returns that same task **untouched** on **200**, so a retry after a timeout cannot make a second Inbox task. The email side keys on `email:` + the `.msg` ref folded onto the placeholders (`email:{onedrive}/mail/house/…msg`) rather than the archiver's `emails.id`, which is a rowid that reshuffles if the index is ever rebuilt; a mail *moved* inside the archive changes its ref and so captures once more.

One-way means what it says: **clearing the flag never removes the task**, and no later pass overwrites a title you edited or a status you moved. A captured task, once real, is yours.

**Deleting a captured task dismisses it.** An archived `.msg` keeps the flag it had when it was saved, so the index offers that mail on every pass for as long as the file exists. Every capture key is therefore also recorded in `capture_keys`, which outlives the task: after a delete the pass counts the mail **dismissed** (in the log, Settings → *Capture into Inbox* and the `capture` status line) instead of landing it again, and a `POST /api/tasks` replay of a deleted capture answers **410** `capture_dismissed`. Closing the task instead (done / cancelled) keeps it, and its history, where it is. Nothing is ever written back to the mail or the message, and completing the task does nothing to either.

**Where you see it** — Settings → *Capture into Inbox* (state word `on` · `checked` · `off`, the reason spelled out when off, and **Check now** for a pass on demand), `GET /api/status` under `capture`, and `tasks mirror status`'s `capture` line. `POST /api/capture/email/run` runs one pass and answers **409** `capture_disabled` with the reason when the poller is off — never a silent no-op. One pass lands at most 200 tasks so a first run against a large archive cannot flood Inbox; the rest arrive on the following passes.
