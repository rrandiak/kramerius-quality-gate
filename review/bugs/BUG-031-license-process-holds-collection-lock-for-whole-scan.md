---
id: BUG-031
former_id: null
category: bug
title: The add/remove-license process holds a collection's lock for the whole scan of its items, so the lock lease expires and edits made to the collection in the meantime are overwritten
area: storage
severity: high
effort: XS               # lock only the RELS-EXT read-modify-write; scan outside it (Solr facet like CollectionsResource: S)
touches: [processes/dnntflag]
contracts: []
data_migration: false
use_cases: [admin]
review_ref: []
upstream: https://github.com/ceskaexpedice/kramerius/issues/1334#issuecomment-6745535189
checked: [source, production]
checked_how: "Read SetLicenseProcess and CollectionsResource at Kramerius 560676c, AkubraDOManager at Akubra 51d821b, HazelcastConfiguration at hazelcast-locks-server e094053; MZK 2026-11-03: one hazelcast-0 IllegalMonitorStateException and one add-license process log, shared by an operator; MZK process-db 2026-11-09: license jobs of the last 30 days; lock hold times and lost updates not counted"
checked_on: 2026-11-09
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-031 — The add/remove-license process holds a collection's lock for the whole scan of its items, so the lock lease expires and edits made to the collection in the meantime are overwritten

> **In one sentence:** when a license is added to or removed from an object that is in a collection, the license process
> recomputes the collection's `contains_license` relations while holding the collection's PID lock. That recompute reads
> every item of the collection and walks each item's ancestors, which can take hours. The lock lease is 120 s, so the
> lock server drops the lock long before the process writes the collection's RELS-EXT back. The process then writes the
> version it read at the start, which discards any change made to the collection meanwhile, and the final unlock fails.
> The collection membership edit in the admin API recomputes the same aggregate correctly, with one Solr query and a
> short lock.

## Upstream issue

Reported as a [comment on kramerius#1334](https://github.com/ceskaexpedice/kramerius/issues/1334#issuecomment-6745535189)
("Reindexace sbírky po zařazení dokumentu trvá hodiny") by MZK on 2026-11-09, not as a new issue: #1334 is open and has
the same root cause. Its fix (`0e3f405f5`, `v7.2.2.4`) moved the membership-edit recompute to the Solr index; the same
commit added this FOXML recompute under the lock to the license process. The comment asks to unify both on the
`CollectionsResource` approach.

## Symptom

The lock server (`hazelcast-0`) logs, when the process finishes a collection:

```
SEVERE: Current thread is not owner of the lock! -> <not-locked>
java.lang.IllegalMonitorStateException: Current thread is not owner of the lock! -> <not-locked>
  at com.hazelcast.concurrent.lock.operations.UnlockOperation.unlock(UnlockOperation.java:75)
  ...
  at com.hazelcast.client.impl.protocol.task.AbstractPartitionMessageTask.processMessage(AbstractPartitionMessageTask.java:67)
```

`<not-locked>` means nobody holds the lock any more: the client unlocks a lock whose lease has already run out.

The process log (`AddLicenseStarter`, shortened, 2026-11-03) shows the target object done in seconds, then one line per
collection item for a long time:

```
11:56:30 SetLicenseProcess addLicense  Adding license 'mzk_public-muo' to uuid:0aa2e014-…
11:56:34 SetLicenseProcess addLicense  Indexed: 15/16
11:56:44 SetLicenseProcess updateAffectedCollections  recomputing contains_licenses for affected collections
11:56:45 SetLicenseProcess collectLicensesFromCollectionItem  collecting licenses from collection item uuid:85ec99a0-…
11:56:45 SetLicenseProcess collectLicensesFromCollectionItem  licenses from collection item uuid:85ec99a0-…: [mzk_public-muo]
11:56:45 SetLicenseProcess collectLicensesFromCollectionItem  collecting licenses from collection item uuid:32f5fba0-…
…
```

## Cause

Kramerius `master` at `560676c`, `SetLicenseProcess` (`processes/dnntflag/.../SetLicenseProcess.java`):

- `addLicense` and `removeLicense` end with `updateAffectedCollections` (`:209`, `:366`). For every affected collection
  it calls `recomputeCollectionContainsLicenses` (`:389–407`).
- `recomputeCollectionContainsLicenses` (`:410–433`) does all of its work inside
  `akubraRepository.doWithLock(collectionPid, …)`:
  1. reads the collection's RELS-EXT (`:413`);
  2. `collectLicensesFromCollectionItems` (`:437–453`): for every `rel:contains` item it calls `re().exists` and then
     `collectLicensesFromCollectionItem` (`:455–498`), which reads the item's RELS-EXT and walks its own parents up to
     the root, one processing-index query, one `exists` and one RELS-EXT read per level;
  3. replaces the `contains_license` relations in the DOM it read in step 1 and writes it back (`:418–431`).

  Step 2 is sequential and grows with collection size × tree depth. An operator reports that it can take hours for large
  collections. Only step 1 and step 3 need the lock.
- Akubra `doWithLock` (`AkubraDOManager.java:406–438@51d821b`) takes the lock with
  `tryLock(waitTimeSecs, leaseTimeSecs)` and always unlocks in `finally`. Both times default to 120 s
  (`HazelcastConfiguration.java:48–49@e094053`). Kramerius overrides them only through `hazelcast.waitTime` and
  `hazelcast.leaseTime` (`AkubraRepositoryProvider.java:38–41`), and neither the chart nor MZK sets
  them.

When step 2 runs longer than 120 s:

1. **The lock server releases the lock.** Any other writer can now take it: the admin API's collection endpoints
   (`CollectionsResource.java:513`, `:613`, `:709`, `:876`, `:972`: add or remove items, clips, thumbnails), or another
   license process on a different member of the same collection.
2. **Lost update.** The license process still writes the collection RELS-EXT it read before the scan. Every change
   written to that RELS-EXT during the scan is lost, such as `rel:contains` added or removed through the admin API, or another
   process's `contains_license`. Nothing logs it.
3. **The final unlock fails.** `lock.unlock()` in the `finally` block throws `IllegalMonitorStateException`. The
   exception is not a `DistributedLocksException`, so the loop in `setLicenseMain` (`:113–117`, `:140–144`) records the
   target PID as broken. The process ends FAILED (`:153`) although the RELS-EXT write was done. The Solr
   `contains_licenses` update for that collection (`:405`), every remaining affected collection and the final commit are
   skipped. Repository and index now disagree.

During the first 120 s, admin writes to the collection wait and then fail with `LockTimeout`. After that they go
through and are overwritten later.

### Two paths recompute the same aggregate; only one does it correctly

A collection's `contains_license` is recomputed on two paths, written separately:

| Path | Trigger | How it computes | Lock held for |
| --- | --- | --- | --- |
| Collection membership edit (correct) | Admin API adds or removes items: `POST {pid}/items` (`addItemToCollection`, `addItemsToCollection`), `DELETE {collectionPid}/items/{itemPid}` and `PUT {collectionPid}/items/delete_batch_items` (`removeItemFromCollection`); calls at `CollectionsResource.java:532`, `:648`, `:922`, `:997` | one Solr facet query over `in_collections:"<pid>"` (`:719–726`, fields `licenses`, `licenses.facet`, `licenses_of_ancestors`, `contains_licenses`), with no lock | only the re-read of the RELS-EXT, `replaceContainsLicenses` (`:810–822`) and the write (`:708–717`): milliseconds |
| License change (wrong) | `SetLicenseProcess` adds or removes a license on a collection member (`:209`, `:366`) | reads every item and walks its ancestors in the repository (`:437–498`) | the whole scan plus the write (`:410–433`): can take hours |

The membership-edit path, `CollectionsResource.updateCollectionContainsLicensesInRepositoryAndSearchIndex`
(`CollectionsResource.java:696–717`), shows the intended pattern: compute without the lock, then lock only the
read-modify-write.

## Evidence and frequency

MZK production, 2026-11-03: an operator shared one `IllegalMonitorStateException ... <not-locked>` from `hazelcast-0`
and the log of an add-license process (license `mzk_public-muo`, target `uuid:0aa2e014-58b5-4c75-81f1-1f1b8a47a45e`).
In that log, the collection recompute started at 11:56:44 and was still listing items when the excerpt ends. The
operator reports that the recompute can take hours on large collections.

MZK process-db, 2026-11-09, license jobs of the last 30 days: 1 114 (`add_license` 870, `remove_license` 244). 6
ended FAILED and 5 of these ran 130–193 s, just over the lease; the 2026-11-03 job ran 193 s. 22 more ran over 120 s
and finished OK (longest 3 133 s); the duration covers the whole process, not only the time under the collection lock.
`hazelcast-0` and the worker Tomcat logs no longer had matching lines on that day.

**Not yet counted:**
- whether all 6 FAILED jobs failed on the expired lock (their process logs);
- how long license processes spend in `updateAffectedCollections`;
- whether any collection was edited during such a run, which would show the lost update.

The 120 s default lease and the `finally` unlock alone are enough for the failure. Any run of the collection recompute
longer than 120 s hits it.

## Impact

- **Data loss in collections.** Admin edits to a collection made while a license process recomputes it disappear without
  an error. Example: items added to or removed from the collection.
- **Wrong license aggregates.** Two license processes that touch the same collection can each overwrite the other's
  `contains_license`, which leaves the collection's aggregate wrong in the repository.
- **A failed process after a successful write.** The process is marked FAILED, and Solr `contains_licenses` of the
  collection is not updated, so search facets and access filters that read it show the old value until the
  collection is reindexed.
- **Blocked admin edits for the first 120 s.** Collection edits fail with `LockTimeout` while the lock is still held.

Raising `hazelcast.leaseTime` to hours stops the lost update. But admin edits to the collection then fail with
`LockTimeout` for the whole run, and the setting applies to every PID lock, so a hung thread can hold any object for
that long. It is a stopgap, not a fix.

## Fix

Keep the scan outside the lock, and lock only the read-modify-write of the collection's RELS-EXT:

```java
private static Set<String> recomputeCollectionContainsLicenses(String collectionPid, AkubraRepository akubraRepository) throws IOException {
    Document snapshot = akubraRepository.re().get(collectionPid).asDom4j(true);
    Set<String> containsLicenses = collectLicensesFromCollectionItems(snapshot, akubraRepository);   // no lock
    return akubraRepository.doWithLock(collectionPid, () -> {
        Document current = akubraRepository.re().get(collectionPid).asDom4j(true);               // fresh read
        // replace only the contains_license relations in `current`, as today on `collectionRelsExt`
        akubraRepository.re().update(collectionPid, new ByteArrayInputStream(current.asXML().getBytes(StandardCharsets.UTF_8)));
        return containsLicenses;
    });
}
```

- The write starts from a fresh read, so other changes survive. The lock is held for milliseconds, so the 120 s lease is
  enough.
- What's left is a smaller race. If the collection's items change during the scan, the aggregate can be stale until the
  next recompute. To close it, compare the `rel:contains` list inside the lock with the snapshot and scan again if it
  changed.
- **Better (S):** replace the scan with what the membership-edit path does, a Solr facet query over `in_collections`, and share
  `replaceContainsLicenses` with `CollectionsResource`. The process commits Solr before the recompute (`:200–206`), so
  the index is fresh. This also removes the hours of item-by-item reads. Check first that the facet result matches the
  item walk. The walk reads only explicit `license` on ancestors, on purpose (comment at `:471–474`), while the facet
  also counts `licenses_of_ancestors`.
- **Separately, in Akubra:** the `finally` unlock should not replace the operation's result or exception. Check
  `lock.isLockedByCurrentThread()` first, or catch `IllegalMonitorStateException`, log that the lease expired, and
  rethrow only if the operation itself succeeded. This is how a caller learns that it lost exclusivity.

## Test

Run with the in-memory Hazelcast from BUG-004's test and `leaseTimeSecs(2)`:

1. Make a collection with a few items, and stub the item walk to sleep 3 s.
2. Run `recomputeCollectionContainsLicenses` in thread A.
3. After 2.5 s, in thread B, take the collection lock, add `rel:contains` of a new item to its RELS-EXT, and write it.
4. Join A.

Before the fix, the new `rel:contains` is gone and A throws `IllegalMonitorStateException`. After the fix, the new item
stays, A succeeds, and the lock is held for well under the lease.

## Missing upstream

The Kramerius part is reported (see Upstream issue). Not reported, a separate issue in `akubra`: `doWithLock`'s
`finally` unlock (`AkubraDOManager.java:434–437@51d821b`) throws when the lease has expired and hides the operation's
own outcome.

## Related

- [BUG-004](BUG-004-lock-client-race-sets-read-only.md): the same `doWithLock`; a different failure (client not
  connected yet).
- [`raw/26-bug-hunt-2.md`](../raw/26-bug-hunt-2.md): notes long operations inside PID-lock callbacks, lock hold times not
  measured.
- [PM-002](../perf-medium/PM-002-coalesce-reads-per-unit-of-work.md): the item-by-item reads of the scan are a case for
  joined queries, if the walk is kept.
