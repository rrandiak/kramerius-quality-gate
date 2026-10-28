---
id: PS-003
former_id: BUG-021
category: perf-simple
title: The CDK request cache keys rows without the user, so its per-user cache holds one user per library, and expired rows are never deleted
area: caching
severity: medium
effort: S                # user in the cache id for per-user rows; fix or drop the unused remove methods
use_cases: [admin, image-open, search, storage]
review_ref: [B1]
upstream: null
checked: [source, production]
checked_how: "Read the CDK cache key at Kramerius 560676c; CDK cache DB and MZK NGINX counts 2026-10-28"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-003 — The CDK request cache keys rows without the user, so its per-user cache holds one user per library, and expired rows are never deleted

> **In one sentence:** the CDK's database cache (`query_cache`) derives each row's id from library, URL and PID only, so the
> forwarded-user lookup that should be cached per user for 30 days keeps a single row per library that every user overwrites,
> and nothing ever deletes expired rows, so the table has grown to 111 GB with a third of it past its expiry.

## Symptom

- On the CDK, the user info call (`GET /client/v7.0/user`) asks every full-access library for the user's licences
  (`forward/user`) whenever the previous lookup was for a different user. MZK receives 1,300–2,400 `forward/user` calls a day.
- The CDK's `query_cache` table is 111 GB and only grows.

## Cause

Kramerius `origin/master` at `560676c` (CDK code in `rest` and `shared/common`):

- **The row id leaves out the user.** `AbstractCDKRequestItem.getId` (`AbstractCDKRequestItem.java:39–54`) is
  `md5("<library>_<url>_<pid>")`. `save` looks the row up by that id and updates it if found
  (`StringCDKRequestItem.java:49–110`, same in `ByteBufferCDKRequestItem.java:51`), including `user_identification` and the data.
- **The per-user lookup has the same id for every user.** `V7ForwardUserHandler.user` builds a fixed URL per library,
  `<forwardurl>/api/cdk/v7.0/forward/user` (`V7ForwardUserHandler.java:65`), with no PID, and saves the response with the
  user's identification (`:88–98`). `ProxyUserHandler.cacheHit` reads with that identification as a filter
  (`ProxyUserHandler.java:31–37`). So user B's save replaces user A's row, and A's next lookup misses. The cache only hits
  when the same user asks twice in a row.
- **Each miss fans out to all libraries, one after another.** `ClientUserResource.findLabels`
  (`ClientUserResource.java:174–208`), called from both branches of `GET /client/v7.0/user` (`:154`, `:158`), loops over all
  enabled full-access libraries and calls `forward/user` on each in turn.
- **Nothing removes rows.** Reads skip rows older than `cdk.cache.item` / `cdk.cache.user.providedBy` days (default 30,
  `AbstractCDKRequestItem.isExpired`, `:124–129`), but `CDKRequestCacheSupport.remove(item)`, `remove(List)` and
  `removeByPid` have no callers anywhere in the codebase. An expired row is only replaced when the same URL is requested
  again.
- **The unused delete is broken too (review B1).** `remove(item)` formats `"delete from query_cache where %d = ?"` with the
  string `ID_COLUMN` (`CDKRequestCacheSupportImpl.java:104`), which throws `IllegalFormatConversionException`; `remove(List)`
  concatenates ids into the SQL (`:118–135`). Neither runs today, but both would break or need care when cleanup is added.

No data crosses users: the user and data columns are written in one statement, and the read always filters by a non-null
user identification (`common_user` for anonymous users, `ProxyHandlerSupport.java:408–425`).

## Evidence and frequency

The CDK's cache database (`cdkcache-postgres`) and MZK's NGINX logs, read-only, on 2026-10-28:

- **One row per library, one user.** `query_cache` has exactly 1 `forward/user` row for each of the 14 libraries, each for
  a single user, all 14 written within 3 seconds (00:15:05–08): one user lookup that fanned out and overwrote every row.
- **Calls reaching MZK.** `forward/user` requests from the CDK to MZK per day, 2026-10-21 to 2026-10-27: 1,607, 1,424, 1,284,
  (no data for 10-24), 570, 2,418, 2,152. That is 0.5–0.9 % of all forward calls. Every library receives the same fan-out.
- **Table size.**

| Kind | Rows | Older than 30 days | Data |
| --- | --- | --- | --- |
| `image/jpeg` (thumbnails) | 7,962,467 | 2,676,541 | 93 GB |
| `application/xml` | 897,843 | 292,503 | 2,036 MB |
| other | 2,686 | 236 | 7.5 MB |
| **total** | **8,862,996** | **2,969,280 (33.5 %)** | **95 GB of data, 111 GB on disk** |

## Impact

- **Latency of the CDK user call.** A lookup that misses waits for up to 14 sequential HTTP calls before the CDK client knows
  the user's licences. Not measured on the CDK side; the CDK's traces are not in MZK's ClickHouse.
- **Load on every library.** Each library answers a `forward/user` call that a working cache would have answered from the
  CDK database. Small in absolute terms (about 2,000 a day at MZK).
- **Storage.** 111 GB of cache that grows without bound; about a third of the rows are expired and will never be read.

## Fix

1. **Key per-user rows by the user.** Add the user identification to the hash in `getId` when it is not `common_user`.
   Shared rows (thumbnails, MODS, saved with `common_user`) keep their current ids, so the existing 8.9 M rows stay valid. The
   14 current `forward/user` rows become orphans and expire.
2. **Delete expired rows.** A periodic `DELETE FROM query_cache WHERE created_at < now() - interval '<max days>'` in batches
   (the `created_at` index exists), on the CDK's scheduler or as an operations CronJob. After the first run, PostgreSQL keeps
   the freed space for new rows; returning the expired third (roughly 35 GB, if expired rows are of average size) to the volume needs `VACUUM FULL` or `pg_repack` in a maintenance
   window.
3. **Fix or delete the unused remove methods.** `%d` → `%s` in `remove(item)`, bind parameters in `remove(List)`, or remove
   both if step 2 is the only cleanup.
4. Optional: call the libraries in `findLabels` in parallel, with a timeout per library.

## Test

- Unit test on `AbstractCDKRequestItem.getId`: two items with the same library and URL and different users get different ids;
  two items saved with `common_user` keep today's id.
- Integration test (PostgreSQL): save user A's and user B's `forward/user` responses, then `find` for A returns A's row.
- Unit test for `remove(item)`: it issues one parameterized delete and does not throw.

## Related

- [PH-001](../perf-hard/PH-001-cache-by-invalidation-need.md): cache tiers by invalidation need; this cache has expiry but
  no invalidation or pruning.
- [PS-001](PS-001-forward-resource-graph-per-request.md): other per-request cost on the CDK forward path.
