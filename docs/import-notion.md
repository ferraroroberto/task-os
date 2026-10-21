# Importing from Notion

`scripts/import_notion.py` (`scripts\import_notion.bat`) is a one-shot, idempotent importer for a Notion tasks database — the way an existing Notion list becomes the master list here. It reads every page with its comments, body blocks and people relation over the Notion REST API (stdlib `urllib`, no SDK), maps them onto the schema and writes through the same `src/tasks_repo.py` layer the API uses.

```powershell
# token: NOTION_API_TOKEN in the OS env or a dotenv file (--env-file, default ./.env)
# database id: --database-id, or NOTION_TASKS_DB_ID in the env / env-file
scripts\import_notion.bat --dry-run --database-id <id> --env-file E:\path\.env    # report only, writes nothing
scripts\import_notion.bat --database-id <id> --env-file E:\path\.env              # import into data\tasks.db
scripts\import_notion.bat --database-id <id> --env-file … --limit 20 --json-dump E:\tmp\export.json   # smoke + keep the raw export
scripts\import_notion.bat --from-json E:\tmp\export.json --db E:\tmp\other.db     # replay a saved export, no API call
```

| Notion | task-os |
| --- | --- |
| `status` not started · In progress · Done | `todo` · `todo` · `done` (+ `done_at` = page `last_edited_time`) |
| `status` empty | `todo` — or `inbox` when `priority` = inbox |
| `priority` high · medium · low · backlog · inbox | `high` · `medium` · `low` · `none` · `none` |
| `recurrent` daily · weekly · monthly · three months · yearly | `daily` · `weekly` · `monthly` · `quarterly` · `yearly` |
| `Date.start` | `due` (date part) |
| `link` | `links` (`kind = web`) |
| page body (paragraph, headings, lists, to-do, quote, code, table, image, divider; nested children) | `description` as markdown — unknown block types degrade to their text |
| comments | `comments` (`author` = the commenter's display name, `ts` = original time, `origin = notion`) in created order |
| first `connection` relation | `people` row (`external_id` = the person's page id) + `person_id` |
| further relations | a comment `also linked: <name>` |
| `created_time` / `last_edited_time` | `created_at` / `updated_at` |

Idempotent on the Notion ids: `tasks.external_id` and `comments.external_id` (schema v3), `people.external_id`. A re-run updates the fields that changed in Notion (logged per field like any other change) and never duplicates a task, comment, link or person; an identical page touches nothing. The first import writes **one** activity row per task (`actor = notion-import`, `field = imported`). `--dry-run` prints the report — counts per status / priority / recurrence, comments, people, anything unmapped or skipped, and what a write would create / update / leave alone — and writes nothing, not even the migration. Unmapped select values are counted and fall back to the default (never dropped silently). The running app picks the new schema up on its next restart (`tray.bat --restart`).
