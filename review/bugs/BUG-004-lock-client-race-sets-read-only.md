---
id: BUG-004
former_id: BUG-028
category: bug
title: Parallel admin writes on a freshly started pod fail while Akubra's lock client is still connecting, and each failure switches the whole instance to read-only
area: storage
severity: high
effort: XS               # publish the client only after it connected; do not set read-only on a local client error
use_cases: [admin, ingest]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read AkubraDOManager at Akubra 51d821b and Kramerius af7209c; MZK curator logs 2026-10-28 (10 failed deletes); in-memory test described, not run"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-004 — Parallel admin writes on a freshly started pod fail while Akubra's lock client is still connecting, and each failure switches the whole instance to read-only

> **In one sentence:** Akubra creates its Hazelcast lock client lazily and makes it visible to other threads before it has
> connected, so writes that arrive in parallel during the first connect fail with a NullPointerException, and Kramerius
> treats every such failure as a lock-server outage and switches the whole instance to read-only until an admin resets it.

## Symptom

The admin client suddenly reports read-only mode with reason `distributedLocksException`. All admin writes on all pods are
refused from then on, although the lock server is healthy. The curator logs show, in the same second or two:

```
SEVERE [http-nio-8080-exec-15] cz.incad.kramerius.auth.thirdparty.ExtAuthFilter.doFilter
  org.ceskaexpedice.akubra.DistributedLocksException: java.lang.NullPointerException: Cannot invoke
  "com.hazelcast.core.HazelcastInstance.getLock(String)" because the return value of
  "org.ceskaexpedice.hazelcast.HazelcastClientNode.getHzInstance()" is null
...
INFO [akubrasync.cluster-] ... Trying to connect to [hazelcast...]:5701
INFO [akubrasync.cluster-] ... HazelcastClient 3.11.2 ... is CLIENT_CONNECTED
```

After `CLIENT_CONNECTED` the errors stop, but the read-only flag stays.

## Cause

Akubra `main` at `51d821b`, `AkubraDOManager.getLockService` (`AkubraDOManager.java:95–113`):

```java
if (hazelcastClientNode == null) {
    synchronized (this) {
        if (hazelcastClientNode == null) {
            hazelcastClientNode = new HazelcastClientNode();                 // :104 field is non-null now
            hazelcastClientNode.ensureHazelcastNode(hazelcastConfiguration); // :105 hzInstance set only after connecting
```

- The client is created on the first `doWithLock` call in the JVM, not at startup.
- The field is assigned at `:104`, before `ensureHazelcastNode` connects (`HazelcastClient.newHazelcastClient`, about
  0.4–2 s). Another thread that calls `getLockService()` in that window passes the unsynchronized `== null` check, gets the
  node, and `getHzInstance()` returns null. `doWithLock` calls `getHzInstance().getLock(pid)` (`:411`), the NPE is caught and
  wrapped as `DistributedLocksException(LOCK_SERVER_ERROR)` (`:412–413`).
- If `ensureHazelcastNode` throws (lock server unreachable at that moment), the half-built node stays in the field. Every
  later lock in that JVM then fails the same way until the pod restarts.
- The field is not `volatile`, so the double-checked locking is broken even after a successful connect.

Kramerius `master` at `af7209cd5`: `AdminApiResource.handleWorkMode` (`AdminApiResource.java:140–144`) sets
`WorkMode(readOnly = true, reason = distributedLocksException)` in the database for every `DistributedLocksException` whose
code is not `LockTimeout`. It is called from 24 catch blocks in `ItemsResource`, `AkubraResource` and
`CollectionsResource` (for example `ItemsResource.java:489` in `deleteObject`). The flag is global: it blocks writes on every
pod (`checkReadOnlyWorkMode`, `AdminApiResource.java:54–58`), although the failure was local to one JVM and said nothing
about the data or the lock server.

## Evidence and frequency

MZK production, 2026-10-28 (times UTC; Tomcat logs are UTC+1):

| Time | Event |
| --- | --- |
| 03:03 | `hazelcast-0` restarted (8th restart in 97 days); most Kramerius pods restarted between 02:43 and 04:59 |
| 04:19, 04:59 | `kramerius-curator-0`, `kramerius-curator-1` started; no locked write on either until 12:37 |
| 12:37:22.1–24.4 | 10 `DELETE /search/api/*` requests on `kramerius-curator` fail with the NPE above (ClickHouse `otel_traces`, error spans); curator-1 also logs the same failure for `AkubraResource.createManagedDatastream` |
| 12:37:23.7 / 25.1 | curator-0 / curator-1 log `CLIENT_CONNECTED`; `hazelcast-0` logs both clients authenticating for the first time |
| 12:30–12:40 bucket | 10 × `UPDATE kramerius.workmode`, one per failed request |

The lock server was healthy throughout. The trigger is the first parallel burst of admin writes on a curator pod after it
starts (a multi-object delete, a bulk datastream upload); single sequential writes never hit it. Because pods restart
together after node or cluster events, this recurs "often" without an obvious cause.

Sources: pod start times (`kubectl get pods`), `hazelcast-0` log, error spans in `otel_traces`, and client lifecycle lines
in the curator Tomcat logs.

## Impact

- **Availability of all admin writes:** one race on one pod blocks editing, deleting and importing on the whole instance
  until an admin notices and clears the work mode.
- The failed requests themselves (deletes, datastream uploads) answer 500 and are not retried.
- If the first connect fails, the pod's writes fail for good until it restarts, and read-only comes back after every reset.

## Fix

1. **Akubra:** build the client in a local variable, connect it, and only then publish it to a `volatile` field. If
   `ensureHazelcastNode` throws, leave the field null so the next call retries.

   ```java
   private volatile HazelcastClientNode hazelcastClientNode;
   ...
   HazelcastClientNode node = new HazelcastClientNode();
   node.ensureHazelcastNode(hazelcastConfiguration);
   hazelcastClientNode = node;
   ```

   Better still, connect in the `AkubraDOManager` constructor (or right after the repository is created), so the first
   request never waits for the connect.
2. **Kramerius:** in `handleWorkMode`, do not set the global read-only mode for `LockServerError` or `LockNull`. Fail the
   request with 503 and log it. Read-only is meant for maintenance or a confirmed lock-server outage, not for a client error
   in one JVM.
3. **Optional, separate:** the Hazelcast 3.11 client gives up after 2 connection attempts, 3 s apart
   (`connectionAttemptLimit` unset → 2 in `ClusterConnector`), and shuts down for good. Akubra never rebuilds it, so a lock
   server outage longer than ~10–15 s breaks locks on that pod until restart. Set `connectionAttemptLimit` to 0 (unlimited)
   in the client config, or rebuild the client when it is not running.

## Test

In-memory, in Akubra (package `org.ceskaexpedice.akubra.core.repository.impl`, so the package-private `AkubraDOManager` is
reachable), no Hazelcast server needed:

1. Open a local `ServerSocket` on a free port that accepts connections and never answers, so `newHazelcastClient` blocks
   for its connection timeout.
2. Build an `AkubraDOManager` from a `RepositoryConfiguration` with the test repository paths (as in the BUG-002 test) and a
   `HazelcastConfiguration` whose only address is that port (`waitTimeSecs` 1).
3. Thread A calls `doWithLock(pid, () -> true)` and blocks inside the connect. After ~200 ms, thread B calls the same.
4. **Before the fix:** B fails at once with `DistributedLocksException`, code `LockServerError`, cause
   `NullPointerException`. When A's connect gives up, a third call fails the same way (half-built node kept).
   **After the fix:** B waits for the same monitor and then fails with the connect error (not an NPE), and a third call
   tries to connect again.
5. Kramerius unit test for `handleWorkMode` with a fake `WorkModeService`: `LockServerError` and `LockNull` must not call
   `setWorkMode(readOnly = true)`.

Running it needs `org.ceskaexpedice:hazelcast-locks-server:2.0`, which is published only to GitHub Packages (a token with
`read:packages`, as for BUG-002). Alternative: build it from `ceskaexpedice/hazelcast-locks-server` with
`./gradlew publishToMavenLocal` and add `mavenLocal()` to Akubra's repositories.

## Related

- [BUG-007](BUG-007-akubra-swallows-storage-errors.md), [BUG-002](BUG-002-unmarshaller-pool-leaks-on-error.md): other
  failure handling in `AkubraDOManager`.
- [KB-005](../known-bugs/KB-005-worker-never-starts-if-registration-fails.md): the same "connect once at first use, never retry" pattern
  in the workers.
- [QOL-002.4](../quality-of-life/QOL-002.4-separate-processes-where-measured.md): with one owner of the repository, cross-JVM locks
  shrink to one place.
