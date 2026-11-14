# Importing from SharePoint

`src/imports/sharepoint.py` (`scripts\import_sharepoint.bat`) is a one-shot, idempotent importer for a SharePoint list — the way a work task list becomes tasks here, **with every item's comments, their replies and the history of its "append changes" text columns**. The built-in *Export to Excel / CSV* loses both, so the importer reads a JSON dump you take yourself, in a browser that is already signed in to the site, through SharePoint's REST API. No app registration, no token and no network access from task-os: the dump file is the only input.

> **The dump is work data.** It holds every title, comment and name in the list. Keep it off any repository, any shared folder and any issue; delete it when the import is done. The importer's report carries counts and the mapping's own values (choice values, display names you must map), never titles or comment text — but the names in it are still real, so do not paste a report anywhere public either.

## 1. Take the export

Open any page of the site in a signed-in browser, open the developer console (F12 → Console), set the two placeholders and run the script. It pages through the list's items, then fetches each item's comments, each comment's replies and each item's versions, and saves one `sharepoint-export.json`.

```js
(async () => {
  const site = 'https://<tenant>.sharepoint.com/sites/<site>';   // the site the list lives in
  const listId = '<list-guid>';                                    // list settings page → the {…} in the URL
  const opts = { credentials: 'include', headers: { Accept: 'application/json;odata=nometadata' } };
  const get = async (url) => {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(res.status + ' ' + url);
    return res.json();
  };
  const all = async (url) => {
    const out = [];
    for (let next = url; next; ) {
      const page = await get(next);
      out.push(...page.value);
      next = page['odata.nextLink'] || null;
    }
    return out;
  };
  const list = `${site}/_api/web/lists('${listId}')`;
  const meta = await get(`${list}?$select=Id,Title`);
  const fields = await all(`${list}/fields?$filter=Hidden eq false&$select=InternalName,Title,TypeAsString,Choices`);
  const items = await all(`${list}/items?$top=500&$select=*,FieldValuesAsText&$expand=FieldValuesAsText,AttachmentFiles`);
  for (const [n, item] of items.entries()) {
    item._comments = (await get(`${list}/GetItemById(${item.Id})/Comments`)).value;
    for (const comment of item._comments) {
      comment._replies = comment.replyCount > 0
        ? (await get(`${list}/GetItemById(${item.Id})/Comments(${comment.id})/replies`)).value
        : [];
    }
    item._versions = await all(`${list}/items(${item.Id})/versions`);
    if (n % 20 === 0) console.log(`${n + 1}/${items.length}`);
  }
  const dump = { exported_at: new Date().toISOString(), site, list: { id: meta.Id, title: meta.Title }, fields, items };
  const link = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([JSON.stringify(dump)], { type: 'application/json' })),
    download: 'sharepoint-export.json',
  });
  link.click();
})();
```

The routes are SharePoint's own: items come from `…/items` (paged), comments from `…/GetItemById(<id>)/Comments` (the `items(<id>)/Comments` route is invalid), replies from `…/Comments(<comment-id>)/replies` and versions from `…/items(<id>)/versions`. Check the comment counts against the *Comments* response, not the `CommentCount` field in version metadata.

## 2. Fill the mapping

Copy `config/sharepoint-mapping.sample.json` to `config/sharepoint-mapping.json` (gitignored, like every real `config/*.json`) and name your list's **internal** column names — the `InternalName` values in the dump's `fields`, which can differ from the titles on screen.

| Key | Meaning |
| --- | --- |
| `title` · `description` · `due` | One column each. `description` is the column's text (HTML reduced to plain text); `due` keeps the date part. |
| `status` · `priority` | `column` plus a `values` table from the list's choice text to a task value (`inbox` `todo` `standby` `done` `cancelled` / `high` `medium` `low` `none`). A value missing from the table is counted and falls back to `todo` / `none`. |
| `person` | A person column: the first name becomes the task's *Person* (the contact it is about). |
| `owner` | A person column plus `members`: display name → a member id of `config.json` (`people`). The install owner's own name maps to the first member and leaves the owner empty, which already means them. A name missing from the table, or a member that does not exist, is counted and the task stays the install owner's. |
| `append_columns` | "Append changes" text columns: each version that added text becomes one comment holding only the new text, with the editor and the version date. |
| `text_columns` | Columns whose URLs also become web links on the task. |

## 3. Dry run

```powershell
scripts\import_sharepoint.bat --from-json E:\tmp\sharepoint-export.json --mapping config\sharepoint-mapping.json --dry-run
```

Reads only (not even the migration runs, and no file is created). The report gives the item count, status and priority as mapped next to their source values, how many items have a due date, a body, a contact and an owner, the link count, comments and versions read, per-column fill counts, a line per item (id, comments, versions) and what a write would create, update or leave alone. **Unmapped** choice values and display names are listed so you can add them to the mapping; run it again until the lists are empty or acceptable.

## 4. Import

```powershell
scripts\import_sharepoint.bat --from-json E:\tmp\sharepoint-export.json --mapping config\sharepoint-mapping.json
```

Writes into `data\tasks.db` (`--db <file>` picks another). Take a backup first, and restart the tray afterwards so the running app has the current schema (`tray.bat --restart`).

| SharePoint | task-os |
| --- | --- |
| Item `Id` | `tasks.external_id` = `sharepoint:<list-id>:<item-id>` (the key a re-run finds the task by) |
| `Created` / `Modified` | `created_at` / `updated_at`; a done item also gets `done_at` = `Modified` |
| Comments, oldest first, each reply right after its parent | `comments` (`origin = sharepoint`, the author's display name, the original time); ids `…:c<id>` and `…:c<id>:r<id>` |
| One entry per version of an append column | `comments` (`origin = sharepoint`, the editor, the version date); ids `…:v<column>:<version-id>`. A version that extends neither end of the previous text is kept whole and counted as a note. |
| URLs in `text_columns` and in comment text | `links` (`kind = web`, de-duplicated) |
| Attachments | `links` back to the file on the site, labelled with the file name; no file is copied |
| The item itself | one `links` entry, *SharePoint item*, built from the dump's `site` and list id at run time |
| First import | one `activity` row per task (`actor = sharepoint-import`, `field = imported`) |

Unknown choice values, people and owners are counted and fall back to the defaults; nothing is dropped silently.

## 5. Re-run before archiving the list

The import is idempotent: run the same command on a fresh export later and only what changed in SharePoint is touched. A changed field is updated (logged per field like any other change), a new comment, reply or version is added, an unchanged item changes nothing. Take a new export, dry-run it, import it, and only then archive the SharePoint list. Changes made in task-os to an imported task's fields are overwritten by the next re-run if SharePoint still holds the old value, so finish the last re-run before editing the tasks here.
