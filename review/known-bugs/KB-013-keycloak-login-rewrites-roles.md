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
checked_how: "Read ExtAuthFilter and role update at Kramerius 560676c; MZK pg_stat counts on group_user_assoc; kramerius#1231"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-013 — Every new session of a Keycloak user deletes and re-inserts all its roles, even when nothing changed

> **In one sentence:** when a Keycloak-authenticated user starts a new HTTP session, Kramerius deletes all of that user's
> role rows and inserts them again without checking whether the roles changed, and clients that do not keep the session
> cookie start a new session on every request, so the `group_user_assoc` table is rewritten thousands of times an hour.

## Symptom

- In the Kramerius DB at MZK, `group_user_assoc` has 210,659 inserts and 208,249 deletes (since the last statistics reset)
  and takes 96 MB, for about 600 users. Every other table is almost write-free.
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
  never cleaned up. With ~600 users this is small; it grows with every distinct user.

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
- Possible duplicate role rows when two pods sync the same user at once. They do not change rights decisions (roles are
  read as a set), but they keep growing the table.

## Fix

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

- The MZK `kramerius-db` replica broke around 2026-09-09; its inactive replication slot keeps all WAL since then on the
  primary (`max_slot_wal_keep_size = -1`). That is an operations issue, not a Kramerius bug, but this churn is what makes the
  pinned WAL grow so fast.
- [QOL-007](../quality-of-life/QOL-007-one-implementation-per-curator-write.md): users and roles are class A writes (one store,
  one transaction).
- Open: the `desirable` table (16,434 inserts, no updates or deletes, 126 MB) looks like an unused feature that still writes;
  not yet investigated.
