---
id: PS-005
former_id: BUG-030
category: perf-simple
title: Listing a user's folders runs one more SQL query, on a second connection, for every folder
area: folders
severity: low
effort: XS
use_cases: [admin]
review_ref: []
upstream: null
checked: [source]
checked_how: "Read FolderDatabase at Kramerius 560676c; not measured"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-005 — Listing a user's folders runs one more SQL query, on a second connection, for every folder

> **In one sentence:** `GET` on the folders endpoint reads the user's folders with one query and then the users of each
> folder with one query per folder, each on a new connection taken while the first is still open, so a user with N
> folders costs N+1 queries and holds two pooled connections for the whole request.

## Symptom

None reported. The folder list gets slower in proportion to the number of folders a user has, and each request holds two
database connections at once.

## Cause

Kramerius `master` at `560676c`, module `folders`:

- `EndpointFolders.getFoldersRelatedToMe` (lines 35–60) calls `FolderDatabase.getFolders(userId)`.
- `FolderDatabase.getFolders` (lines 39–56) opens a connection, runs the join of `folder` and `folder_user` and, inside the
  `while (rs.next())` loop, calls `getFolderUsers(uuid)` for each row (line 50).
- `getFolderUsers` (lines 76–92) takes **another** connection from the provider and runs
  `SELECT * FROM folder_user WHERE folder_uuid = ?`.

`getAllFolders` (lines 18–35) has the same loop and a `TODO` in Czech, "optimize getting the users with a join". It has no
callers at `560676c`. `getFolderByUuid` (lines 58–74), used by eight endpoints, also opens the second connection while the
first is open, for one extra query.

Noted as an unmeasured N+1 in [run 18](../raw/18-folders-source-audit.md).

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only, not measured. MZK has 3,536 folders ([KB-016](../known-bugs/KB-016-folder-counts-and-orphans-after-delete.md)); the number
of folders per user and the endpoint's call rate decide whether this matters. To measure, read-only on users-db:

```sql
SELECT percentile_disc(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY n) AS p50_p95_p99, max(n) AS max_folders
FROM (SELECT user_id, count(*) AS n FROM folder_user GROUP BY user_id) x;
```

## Impact

Latency of the folder list for users with many folders, and twice the connection use per request, which can exhaust the
pool sooner under load. No data is wrong.

## Fix

Read the users of all listed folders in one query on the same connection, after the folder query:
`SELECT folder_uuid, user_id, user_role, created_at FROM folder_user WHERE folder_uuid = ANY(?) ORDER BY created_at DESC`,
grouped into a map by `folder_uuid`. Let `getFolderByUuid` pass its open connection to `getFolderUsers`. Delete the unused
`getAllFolders`.

## Test

Folder database test with a connection provider that counts `get()` calls and statements: a user with 3 folders, each
with 2 users. Before the fix: 4 statements, 4 connections, 2 open at once. After: 2 statements, 1 connection, the same
`Folder` list in the same order.

## Related

- [PM-002](../perf-medium/PM-002-coalesce-reads-per-unit-of-work.md): the general rule this is one case of.
- [KB-016](../known-bugs/KB-016-folder-counts-and-orphans-after-delete.md): other folder statements that run on separate connections.
