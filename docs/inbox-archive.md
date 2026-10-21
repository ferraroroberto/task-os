# Archive the Inbox

The last manual chore: filing the Outlook Inbox one mail at a time. Settings → **Email archiving** (the Archive tab until #397) does the whole tray in one press — every mail is written into an archive folder of [email-archiver](https://github.com/ferraroroberto/email-archiver)'s, moved to Outlook's *Archive* folder and tagged, and the run is recorded so you can read what happened and undo any single mail. *I finished my mails, I press Archive, I read what went where, I fix the one or two that are wrong, and I never file a mail by hand again.*

**The screen.** Press *Archive Inbox now* (optionally bounded to the **first N mails**) and the button disables, a progress line follows the run and the report fills in when it lands; a second press while one is going says so, because one Outlook takes one run at a time. Each row then offers exactly the review levels its own state allows — a control that the API would refuse is not drawn:

| Row state | Accept | Move to… / File it… | Retry | Revert |
| --- | --- | --- | --- | --- |
| `archived` · `moved` | – (finished, not reviewed) | into any *other* folder | – (nothing half-done) | deletes the files, mail back to the Inbox |
| `needs_review` | marks it seen (and teaches the folder it had) | files it for the first time — no undo leg | – (nothing on disk) | – (nothing on disk) |
| `failed` | marks it seen | re-files it | when files were written — sends the same decision again and finishes the move | when files were written |
| `reverted` | – | – | – | – (back in the Inbox, the next run owns it) |

A row that has already had its human stops asking for one (#168): a `needs_review` mail you accepted reads **reviewed**, offers no *Accept* and no *File it…*, and says *nothing left to do* where its buttons were — so *Accept all (N)* counts exactly the rows still offering *Accept* instead of drifting from them. It is still in the Inbox and the next run owns it.

**A refused move is one tap from done (#174).** `apply` writes the `.msg` *before* it moves the mail, so Outlook refusing the move (`move_failed`) leaves the file on disk and the mail in the Inbox — and every later `plan` then reports that mail `already_archived`, so no run would ever offer it again. Two things close the loop. **Retry** on such a row re-sends the *same* decision — same message, same folder, same naming form, nothing re-ranked — and the archiver finishes it: it writes nothing, reuses the file it already wrote, moves the mail and tags it. The row becomes `archived` keeping its files and the sequence number the first attempt allocated (a reuse allocates none), and the error text stays on screen until that actually happens; a second refusal keeps the row `failed` with the archiver's newer message, which is the one that says whether restarting Outlook is what is left to try. And a **run** that meets a mail the index already has *and* which the plan still reports `in_inbox` finishes it the same way rather than recording it as done — it reads **finished a mail already on disk**, with no rank and no new file. Accepting a `failed` row is not finishing it: seeing a mail does not take it out of the Inbox, so *Retry* stays offered on a row already marked seen.

*Move to…* lists the candidates the run already ranked (no re-plan — they are stored on the row) and *Other folder…* opens the same folder-index picker the drawer and quick-add use. The one-line **hint** beside it is optional and is what the next run remembers. Everything that touches a file asks first.

Everything on the screen is also the API, and reading a past run needs no archiver on the machine at all:

**task-os never imports the archiver.** It spawns that repo's `main_batch.py` in the archiver's own venv and reads back one JSON document — `plan` (read-only, ranks folders for every Inbox mail), then `apply` (files, moves and tags the decided ones), then the archiver's `main_scan.py --no-ui` so its index learns the new files. Every verb drives Outlook over COM, and a COM modal blocks whatever thread raises it, so a stuck Outlook is a child process this app kills on `archive.timeout_seconds`, never a wedged webapp. The archiver keeps sole ownership of Outlook, of the filenames and of its index; task-os only decides *which folder*, and hands the candidate's own `date_prefix` straight back so the destination's naming style is the archiver's call, not this app's.

```powershell
curl.exe -X POST "http://127.0.0.1:8448/api/archive/run" -H "Content-Type: application/json" -d '{\"limit\": 1}'
curl.exe "http://127.0.0.1:8448/api/archive/runs"
```

**Start with `limit`.** One run, one mail, then look at it and undo it — trust in something that moves your mail is built on an undo you have actually seen, not on a promise. `limit` caps the mails a run touches, in the archiver's own plan order, and rides either the JSON body or `?limit=`.

**Which folder is a two-layer decision.** The archiver's suggester is a search engine — full-text match, thread continuity, folder-name similarity — and it cannot read a mail. So the ranked candidates go to the local model (`archive.model` through the same hub `ai.base_url` names), in batches of `archive.batch_size`, and it answers with **an index into that list**, a confidence and a one-line reason. It can never name a folder, invent one, reach outside the archive tree or compute a date: it only picks a number, and the path is resolved here from the archiver's own output. The answer is JSON validated whole — exactly one pick per mail in the batch, every index in range, every confidence a number in [0, 1] — because the hub refuses `response_format: json_schema` on the open-weight models, so the validator *is* the contract. A pick below `archive.confidence_threshold`, or an explicit *none of these fits*, leaves the mail in the Inbox as `needs_review` with the model's own words as the reason.

**It learns from every correction.** A `move` that lands, and an `accept` on a `needs_review` mail that had a folder, write an `archive_corrections` row — subject, sender, the folder the system chose, the folder you chose and your optional one-line `hint`. The last `archive.examples` of them ride the next run's prompt as few-shot lines (*mail "…" from … → suggested A, chosen B, hint: …*), oldest first so the block only grows at its tail. Correct it once and the next run of the same kind of mail follows you. Each run records `agreement` — the share of ranked mails the model filed exactly where the suggester would have — so a run whose picks are all rank 0 is visibly a run the model added nothing to, and the accept rate over time is what says when the ranking can be trusted unread.

**A hub that is down does not stop a run.** A batch the model cannot rank — hub off, unreachable, too slow, or answering something the validator refuses — falls back to the archiver's own top candidate for **that batch only**, with the reason on every mail in it ("the local model could not rank this batch (`ai_invalid_response`) — the archiver's own ranking was used") and the classified failure in the run's `error`. Filed by a search engine and filed by a model that read it are different facts, and the report never shows one as the other.

> **Model choice is a measurement, not a preference.** The default is `claude_haiku`: over three live runs of the same seven-mail Inbox it answered validly 3/3 in 29–60 s. `agentic_light_nothink` managed 2/3 — an open-weight model emits its reasoning as ordinary output tokens and one run in three never reached the JSON inside the 6000-token budget — and plain `agentic_light` never finished reasoning at all. Both are one config edit away for an install that wants to stay entirely local, and the degrade path above is exactly what a run with one looks like when it misses. `ai_timeout_seconds` (180) is that request's own bound: `ai.timeout_seconds`' 30 s would call a working model a dead hub.

Each mail ends in one of five states, and the run row counts them:

| State | What it means |
| --- | --- |
| `archived` | filed on disk and moved in Outlook — or already filed per the archiver's index and finished from it, the existing file reused and nothing written |
| `needs_review` | left in the Inbox: the model's confidence was below `archive.confidence_threshold`, it said none of the ranked folders fits, or the archiver ranked none at all |
| `failed` | the archiver refused or broke on this mail, with its own code in `error` (`move_failed` — the files are on disk and the mail is still in the Inbox; `category_failed` — filed and moved, only the tag missing; `not_in_inbox`; `archive_failed`). Still revertible **and retryable** when files were written: `apply` fills them in *before* the move on purpose |
| `reverted` | the files are gone and the mail is back in the Inbox |
| `moved` | re-filed into a folder you picked — an undo followed by a fresh filing |

**A mail is filed once.** Identity is the Internet Message-ID (an Outlook EntryID is rewritten by the very move `apply` performs), and a partial unique index covers `archived` + `moved`, so a second run over a mail this database has already filed writes nothing at all — no row, no child call. A reverted mail is free to be archived again.

Four failures you can tell apart, because the fix differs for each: *not configured here* (409 with the reason — no `archive.repo`, no venv Python, no `main_batch.py`), *Outlook unreachable* (the child's own exit 2), *timed out*, and *a run already in flight* (409 — one Outlook, one child at a time; `revert` and `move` take the same lock). A fifth is deliberately **not** fatal: if the archiver's index rescan afterwards fails, the mails are still filed, so the run finishes `done` and carries the rescan's failure in its `error`. Filed-but-not-confirmed is its own state, never folded into a clean run.

## Renumbering, and the paths it heals

The `NNN` prefix on an archived mail is meant to be browsable: open a folder, read down the list, read the thread in the order it happened. Two ordinary operations break that — a `revert` leaves a hole, and an `apply` always takes the highest number even for a mail older than everything already filed. The archiver repairs it (`renumber`), and task-os asks for the repair on both verbs that cause it: `archive.renumber` (default true) puts `--renumber` on the `apply` and the `revert` it spawns.

**Asking for it means healing after it.** A renumber renames files, the archiver updates its own index and nothing else, and this app stores a `.msg` path in three places — the run item's `files`, the email link's ref on a captured task, and that task's `external_id`. So every rename in the map the archiver returns is applied to all three in the same pass (`apply_renumber_map`), and the triggering row's reason says so: *… · renumbered 4 file(s) in heating*. Without it a revert would delete the wrong file, a chip would open nothing, and the next capture poll would land the same mail a second time under its new name. (The capture key moves even when the task was already deleted, so a dismissed mail stays dismissed under its new name.) The map is read defensively: a document without one means nothing moved (that is every archiver build before the feature), an empty list for a folder means *already in order*, and a folder the archiver **refused** to renumber is logged by name — "nothing to do" and "this folder was left alone" are two different facts.

A map produced outside a run — `main_batch.py renumber --folder …` by hand, or the one-off repair of a folder that was already ragged — goes through the same heal from a file:

```powershell
& .\.venv\Scripts\python.exe scripts\apply_renumber_map.py <map.json> --dry-run
& .\.venv\Scripts\python.exe scripts\apply_renumber_map.py <map.json>
```

`--dry-run` prints the rows it *would* rewrite per table and touches nothing; the heal is idempotent, so running it twice is a no-op rather than a mess.

`GET /api/status`'s `archive` key (and `tasks mirror status`) says whether this install can archive at all, what the last run did, and whether one is running now — it is what the sheet's head renders, what the Settings row and header read and what the palette's *Go to Archive* hint reads (*Go to Archive* opens the sheet). An install without the archiver shows the reason and a disabled button, never a dead press. Config changes need a restart — `tray.bat --restart` — like every other block here.

**Where you see it, without opening the sheet** — the Settings list's *Email archiving* row (#167, #397) carries the run's state word (`off` · `on` · `running` · `error` · `NN% agreed` once a run recorded how often the model and the archiver's own ranking agreed), the Settings header names what the last run left for you (*3 mails need you*), and the palette's *Go to Archive* hint says the same. Inside the sheet, one home per reading: the archiver's state with the model, its batch size and the remembered corrections, where the archiver checkout lives, the threshold with the candidate count, the last run (planned / filed / need you / failed, its agreement and its error when it has one) and what the runs on the picker add up to. Not configured says why, in the same place every other service does. A run the sheet did not start (another device) is followed as soon as Settings re-reads the service: the row reads *running* and the button goes out until it lands; a press that arrives after another device already started one gets the API's *one Outlook, one run at a time* back as a toast and then follows that run.
