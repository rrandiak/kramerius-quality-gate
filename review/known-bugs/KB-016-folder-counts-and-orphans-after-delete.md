---
id: KB-016
former_id: BUG-022
category: known-bug
title: Removing items from a folder never lowers its item count, and deleting a folder leaves its items behind
area: modularization     # folders module; see QOL-002
severity: low
effort: S                # folder writes in one transaction with explicit recount and item delete; one-off reconcile SQL
use_cases: [admin]
review_ref: [B10, B22, B21, B23]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1300
checked: [source, production, upstream-report]
checked_how: "Read the folders module at Kramerius 560676c; MZK users-db read-only counts 2026-10-28; kramerius#1300"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-016 — Removing items from a folder never lowers its item count, and deleting a folder leaves its items behind

> **In one sentence:** the trigger that maintains `folder.items_count` runs on deletes but only recounts on inserts and
> updates, and deleting a folder removes its users and the folder row but not its items, so at MZK 48 folders show more items
> than they hold (18 of them show items while empty) and 233 items of 79 deleted folders are left in the table.

## Symptom

A user removes documents from one of their folders in the client. The folder still shows the old number of
items. A folder emptied this way still shows a non-zero count. The count goes back to the right value only when an item is
added again, because the insert recounts.

## Cause

Kramerius `origin/master` at `560676c`, `folders` module:

- **The trigger ignores deletes.** `init_db.sql:26–44` installs `update_folder_items_count_and_updated_at` as an
  `AFTER INSERT OR UPDATE OR DELETE` trigger on `folder_item`, but the function body recounts only
  `IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE'` (`:29`), using `NEW.folder_uuid`. On DELETE, `NEW` is null and nothing happens.
  `removeFolderItems` (`EndpointFolders.java:346`) deletes item rows one by one through `FolderDatabase.removeFolderItem`
  (`:384`, `FolderDatabase.java:183–192`).
- **Folder delete skips the items.** `deleteFolder` (`EndpointFolders.java:246`) calls `db.deleteFolderUsers` and
  `db.deleteFolder` (`:268–269`), each on its own connection. Nothing deletes from `folder_item`, and the schema has no
  foreign key from `folder_item` to `folder` (`init_db.sql:11–16`).
- **Fixing `init_db.sql` alone would not reach existing installs.** `FolderDatabaseInitializer.initDatabase` runs the script
  only when the `FOLDER` table does not exist yet (`FolderDatabaseInitializer.java:39–40`).
- **Same pattern, not observed at MZK:** folder creation inserts the folder and its owner on separate connections (B21), and
  batch add inserts items one by one after a single snapshot, so a duplicate ID fails mid-batch (B23). Every folder write is a
  sequence of auto-committed statements.

## Evidence and frequency

MZK production, `users-db` (the folder tables live there, not in the `kramerius` database), read-only query on 2026-10-28.
The deployed trigger function is the same as in source (no DELETE branch, no `OLD`), and there are no foreign keys on the
folder tables.

| Check | Result |
| --- | --- |
| Folders / items / user rows | 3,536 / 23,005 / 3,542 (3,536 owners, 6 followers) |
| Folders whose `items_count` is wrong | **48** (1.4 %), all too high; 95 items in total, at most 15 in one folder |
| Folders that show items but are empty | **18** |
| Items whose folder no longer exists (B22) | **233** in 79 deleted folders (1 % of all items) |
| Folders without an owner (B21) | 0 |

Folders are in steady use: 450–1,600 items added a month over the last 12 months, in 100–250 folders a month.

## Impact

- Users see wrong item counts on 1.4 % of folders, including empty folders that look non-empty.
- Orphan items are invisible garbage (folder UUIDs are not reused); they only cost space and make reports wrong.
- No data loss; the defect only affects folders.

## Fix

1. **Do the folder writes in one transaction, and maintain the count in Java.** In `FolderDatabase`, remove items and
   recount `items_count` on the same connection and transaction; delete a folder's items, users and row together. This
   needs no schema change, so it works on existing installs as deployed.
2. **Reconcile existing data once:** recount `items_count` for all folders and delete `folder_item` rows without a folder.
   Ship it as an upgrade step in `FolderDatabaseInitializer` (it already receives a `VersionService`, unused) or as an
   operator SQL script.
3. Optional, later: fix the trigger (recount `OLD.folder_uuid` on DELETE) and add a foreign key with `ON DELETE CASCADE`
   after step 2 has removed the orphans. Both are schema changes that need an upgrade step, so step 1 alone is the smaller fix.
4. Same transaction for create (folder + owner, B21) and for batch add with de-duplicated input (B23).

## Test

PostgreSQL integration test on the folders schema:

- Add three items, remove one: `items_count` is 2 and equals `COUNT(*)`.
- Remove all items: `items_count` is 0.
- Delete a folder that has items: no `folder_item` or `folder_user` rows with its UUID remain.
- Batch-add a list containing the same new ID twice: the batch either adds it once or adds nothing.

## Related

- [QOL-002](../quality-of-life/QOL-002-modularize-in-four-levels.md): folders are the first candidate if a module is ever
  extracted; these fixes should come before any extraction.
