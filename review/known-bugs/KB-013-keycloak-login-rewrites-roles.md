---
id: KB-013
former_id: BUG-014
category: known-bug
title: Every new session of a Keycloak user deletes and re-inserts all its roles, even when nothing changed
area: security
severity: medium
effort: S                # KeycloakUserSupport + DatabaseUserManager.changeRoles; a unique constraint is a small DB migration
use_cases: [admin, search, image-open]
review_ref: []
upstream: https://github.com/ceskaexpedice/kramerius/issues/1231
checked: [source, production, upstream-report]
checked_how: "Read ExtAuthFilter and role update at Kramerius 560676c; MZK pg_stat counts on group_user_assoc (2026-10-28, 2026-11-10); curator traces by client; usersync agent counters on public pods; kramerius#1231"
checked_on: 2026-11-10
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-013 — Every new session of a Keycloak user deletes and re-inserts all its roles, even when nothing changed

> **In one sentence:** when a Keycloak-authenticated user starts a new HTTP session, Kramerius deletes all of that user's
> role rows and inserts them again without checking whether the roles changed, and clients that do not keep the session
> cookie start a new session on every request, so the `group_user_assoc` table is rewritten thousands of times an hour.

## Symptom

- In the Kramerius DB at MZK on 2026-11-10, `group_user_assoc` took ~140,000 inserts an hour (two `n_tup_ins` snapshots,
  53.7 min and 11.3 min apart: ~137k/h and ~142k/h), 25.5 million since the counters were last loaded, and 104 MB.
  `user_entity` has 24,677 users. Every other table is almost write-free. Deletes are not a clean measure, because the table
  is also emptied by hand from time to time; inserts come only from Kramerius.
- In the curator traces of one hour on 2026-11-10, 20,203 of the 20,262 requests that triggered a role rewrite (99.7 %) came
  from AltoEditor (`ReactorNetty/1.2.14`, Bearer token, no cookie). That is ~7 inserts per request, one per role of its
  service account. 255,867 `group_user_assoc` spans came from curator against 110 from the public pods, because the public
  pods run the MZK `usersync-throttle-agent` (see Fix) and curator does not.
- `group_user_assoc` holds 42 duplicate `(user_id, group_id)` pairs (2026-11-10), so the concurrent-sync race below happens.
- In the curator traces (2026-10-27, 21:18–22:25 UTC, 67 minutes): 1,880 `DELETE kramerius.group_user_assoc` and 1,504
  `INSERT kramerius.group_user_assoc` spans.
- The Kramerius DB is 238 MB, but its primary writes about 2.2 GB of WAL a day (106 GB from 2026-09-09 to 2026-10-28). This
  table is the only high-churn table in it.

## Cause

Kramerius `origin/master` `560676c`, module `security/authfilters` and `shared/common`:

- `ExtAuthFilter.doFilter` runs the third-party user sync once per HTTP session: when the session attribute
  `third_party_user` is not `"true"`, it calls `storeUserPropertiesToSession` (`ExtAuthFilter.java:52–59`).
- `KeycloakFilter` uses `KeycloakUserSupport` (`KeycloakFilter.java:52`). Its `updateExistingUser` calls
  `usersManager.changeRoles(u, kUser.getRoles())` whenever the user has any Keycloak roles (`KeycloakUserSupport.java:53–57`).
  There is no comparison with the roles already stored. The older `KeycloackUserSupport` does compare first
  (`KeycloackUserSupport.java:67–81`) but is not the one in use.
- `DatabaseUserManager.changeRoles` deletes every current role row of the user, then inserts one row per role, in one
  transaction (`DatabaseUserManager.java:1032–1068`; SQL `disassociateRole` and `associateRole` in `udatabase.stg:527–541`).
- A client that does not send the session cookie back (an API client with a bearer token, a cross-origin call without
  credentials) gets a new session on each request, so the delete and re-insert happens on each request.

Two side effects of the same code:

- `group_user_assoc` has only a surrogate primary key (`initsecdb.sql:49–53`); nothing prevents duplicate
  `(user_id, group_id)` rows. The per-user lock is per JVM (`AbstractThirdPartyUsersSupport.java:112`), so two curator or
  public pods can sync the same user at the same time.
- `userLocks` and `credentials` (`AbstractThirdPartyUsersSupport.java:112`, `:125`) are maps keyed by user name that are
  never cleaned up. They hold one entry per distinct user name since the JVM started (24,677 users in `user_entity`).

## Evidence and frequency

Seen in production at MZK (counts above). Read-only checks on the primary:

```sql
-- churn on the table
SELECT n_tup_ins, n_tup_upd, n_tup_del, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_stat_user_tables WHERE relname = 'group_user_assoc';
-- duplicate role rows, if any
SELECT count(*) FROM (SELECT user_id, group_id FROM group_user_assoc GROUP BY 1, 2 HAVING count(*) > 1) d;
```

## Impact

- Write load and WAL volume on the Kramerius DB out of proportion to its size; at MZK this turned a broken replica's
  pinned WAL into 106 GB in seven weeks (see Related).
- Table and index bloat; autovacuum keeps cleaning a table that should almost never change.
- Login latency: every new session pays for N deletes and N inserts in a transaction, plus the role lookups.
- Duplicate role rows when two pods sync the same user at once (42 pairs at MZK on 2026-11-10). They do not change rights
  decisions (roles are read as a set), but they keep growing the table.

## Fix

0. Consider not storing Keycloak users' roles at all. The session user's roles come from the token
   (`Keycloak3rdUser.toUser`), and `group_user_assoc` (view `user_group_mapping`) is read only by
   `DbCurrentLoggedUser.tryToLogDB`, a fallback when the filter has not put a user into the session, and by
   `DatabaseUserManager` for local accounts. Read from the code paths, not checked against every caller.
1. In `KeycloakUserSupport.updateExistingUser`, compare the stored role names with the Keycloak roles as sets, and call
   `changeRoles` only when they differ. Do the same in `CDKUserSupport.updateExistingUser`, which reads the stored roles and
   then rewrites them anyway (`CDKUserSupport.java:55–62`). The Shibboleth variant already compares
   (`InternalThirdPartyUsersSupportImpl.java:36–44`).
2. In `changeRoles`, write only the difference: delete roles that are gone, insert roles that are new.
3. Add a unique constraint on `group_user_assoc (user_id, group_id)` after removing existing duplicates, and use
   `INSERT … ON CONFLICT DO NOTHING`.
4. Optional: remember the last synced role set per user for a short time (for example the token lifetime), so cookie-less
   API clients do not resync on every request.

## Test

- Unit test: a user whose stored roles equal the Keycloak roles; a new session must issue no `DELETE` or `INSERT` on
  `group_user_assoc`.
- Unit test: add one role and remove one in Keycloak; the next session must delete exactly one row and insert exactly one.
- Staging: replay an hour of curator API calls without cookies; `n_tup_ins` and `n_tup_del` of `group_user_assoc` must stay
  flat.

## Related

- Upstream: comment with the exact cause, since when and MZK numbers on kramerius#1231,
  https://github.com/ceskaexpedice/kramerius/issues/1231#issuecomment-6773230955 (2026-11-10).
- The check was lost in [`39cc8ff`](https://github.com/ceskaexpedice/kramerius/commit/39cc8ffb32bd8474d8ef6985998a177e1866dc60)
  "Issue #908" (2022-10-03, first tag `v7.0.14`), which commented out the role comparison added in `6a7c086` (2021-12-15, `v7.0`).
- MZK workaround: the `usersync-throttle-agent` javaagent makes the set comparison before `updateExistingUser` and skips the
  rewrite on equal roles. On the public pods it skipped 2.02 million of 2.40 million syncs (84 %) by 2026-11-10; curator
  does not load it yet.

- The MZK `kramerius-db` replica broke around 2026-09-09; its inactive replication slot keeps all WAL since then on the
  primary (`max_slot_wal_keep_size = -1`). That is an operations issue, not a Kramerius bug, but this churn is what makes the
  pinned WAL grow so fast.
- [QOL-007](../quality-of-life/QOL-007-one-implementation-per-curator-write.md): users and roles are class A writes (one store,
  one transaction).
- Open: the `desirable` table (16,434 inserts, no updates or deletes, 126 MB) looks like an unused feature that still writes;
  not yet investigated.
