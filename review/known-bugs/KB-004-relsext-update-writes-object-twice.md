---
id: KB-004
former_id: BUG-010
category: known-bug
title: Updating RELS-EXT saves the object twice, first without RELS-EXT, so a crash in between deletes it for good
area: storage
severity: high
effort: S                # Akubra: replace the datastream in memory and save the object once
use_cases: [admin, ingest, storage]
review_ref: [B24]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1371  # symptom first in process-platform#14
checked: [source, upstream-report, test]
checked_how: "Read RELS-EXT update at Kramerius 560676c and Akubra 51d821b; incident reported in process-platform#14; Akubra test at 51d821b (fixture repo, in-memory Hazelcast, mocked processing index): deleteDatastream alone leaves 0 RELS-EXT, createXMLDatastream alone replaces it with exactly 1"
checked_on: 2026-11-10
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-004 — Updating RELS-EXT saves the object twice, first without RELS-EXT, so a crash in between deletes it for good

> **In one sentence:** Akubra updates an XML datastream by first saving the whole object without it and then saving the object
> again with the new version, so if the JVM dies or the second save fails between the two, the object stays in storage with
> no RELS-EXT, which is what happened at MZK when a worker restarted during a licence change.

## Upstream issue

[kramerius#1371](https://github.com/ceskaexpedice/kramerius/issues/1371) "Objekt natrvalo stratí stream (napr. RELS-EXT),
keď proces spadne počas jeho úpravy", opened by MZK on 2026-11-10 from this entry. Filed in `kramerius` although the fix is
in Akubra, because Akubra fixes are tracked through Kramerius issues. It covers all three `update*Datastream` methods, the
June 2026 incident from [process-platform#14](https://github.com/ceskaexpedice/process-platform/issues/14) (symptom only,
wrong repository), the Akubra test, since when (Kramerius `eb54993a4`, `v7.0.23`; Akubra `6709f63`, `v1.0-rc1`) and the fix
below.

## Symptom

At MZK three licence jobs ran one after another on the same document
([process-platform#14](https://github.com/ceskaexpedice/process-platform/issues/14)):

1. remove licence `onsite`: finished;
2. add licence `public`: the worker restarted while it ran;
3. add licence `public` again: failed, the document **has no RELS-EXT**.

Without RELS-EXT the object has no model, no parent and child relations and no licences: it drops out of the tree, the
processing index and the search index on the next reindex. There is no older version to restore from.

## Cause

`ceskaexpedice/akubra` at `51d821b`:

- `AkubraRepositoryImpl.updateXMLDatastream` (`AkubraRepositoryImpl.java:134–145`), used by `RelsExtHelperImpl.update` for every
  RELS-EXT change, does two separate operations under the per-PID lock:
  1. `coreRepository.deleteDatastream(pid, dsId)` → `AkubraDOManager.deleteStream`, which removes the datastream from the object
     and **saves the whole FOXML** without it (`AkubraDOManager.java:189–215`, save on line 208);
  2. `coreRepository.createXMLDatastream(…)` → `AkubraDOManager.write`, which **saves the whole FOXML again** with the new
     datastream (`AkubraDOManager.java:231–260`, save on line 253).
- Each save is a safe overwrite of the FOXML file, so each one is atomic on its own. The pair is not. Between them, storage holds
  a valid object with no RELS-EXT.
- If the JVM is killed in that gap (worker pod restart during a deploy, OOM, `kill` of the job), the second save never happens.
- If the second save fails, `AkubraDOManager.write` catches the exception, logs "Could not replace object in Akubra" and returns
  normally ([BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md)), so the job continues as if RELS-EXT was written.
- The per-PID Hazelcast lock only keeps other writers out; it does not undo step 1.

The same delete-then-create sequence is used by `updateManagedDatastream` (line 172), which also deletes the old datastream
**file** before saving, and `updateExternalDatastream` (line 204).

Kramerius callers that update RELS-EXT this way (`origin/master` `560676c`): `SetLicenseProcess` (lines 281, 427),
`LicenseHelper` (line 69), `DeleteTreeProcess` (line 409), and the admin API `ItemsResource` (line 425).

## Evidence and frequency

- Observed at MZK in June 2026 ([process-platform#14](https://github.com/ceskaexpedice/process-platform/issues/14)); the timing
  matches a worker restart during the licence job.
- The gap is short (one FOXML save), but a licence job updates RELS-EXT of every object in a tree, often thousands, and worker
  restarts happen on every deploy, so a job running during a deploy has a real chance to hit it.
- Since 2026-10-27 the job JVMs are traced with spans on Akubra calls (chart 1.3.2); a trace that has the `deleteDatastream` save
  but ends before the following write would show it.

## Impact

- Permanent loss of RELS-EXT for the affected object: model, relations, licences. Reconstruction needs a backup or manual work.
- Children of a damaged parent lose their place in the tree on the next processing index rebuild.
- Licence jobs are the most exposed, and they are the ones curators run in bulk.

## Fix

`createXMLDatastream`, `createManagedDatastream` and `createExternalDatastream` already remove the old stream with the same
ID from the in-memory object (`createDatastreamHeader`, `CoreRepositoryImpl.java:309–316@51d821b`) and then save once. So:

1. In all three `update*Datastream` methods (`AkubraRepositoryImpl.java:134–145`, `:166–176`, `:198–208`), drop the
   `deleteDatastream` call. Storage then holds either the old or the new stream, never none.
2. Managed streams: the new content is stored under the same key (`pid+dsId+dsId.0`, `convertManagedStream`), so the file
   is overwritten in place. Files of older versions with another version ID should be removed only after the FOXML save.
3. RELS-EXT: the processing index needs no `deleteByRelationsForPid` first; the rebuild in `createXMLDatastream`
   (`CoreRepositoryImpl.java:228–242`) deletes relations that are no longer in the new RELS-EXT. This also removes the
   window in which the relations are gone from the processing index ([BUG-010](../bugs/BUG-010-processing-index-submits-partial-rebuild.md)).
4. Make the save throw on failure ([BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md)).

## Test

Run on 2026-11-10 at Akubra `51d821b`, set up like `DatastreamWriteTest` (fixture repository, in-memory Hazelcast,
mocked processing index); the test file is kept outside the repository:

- `deleteDatastream(PID_MONOGRAPH, "RELS-EXT")` alone: the stored object has 0 RELS-EXT streams (the state after a crash
  between the two saves).
- `createXMLDatastream(obj, "RELS-EXT", …)` alone on an object that has RELS-EXT: the stored object has exactly 1, the new
  one. So `deleteDatastream` is not needed for the replacement.

Still to write:

- Unit test with a storage stub that throws on the second `addOrReplaceObject` call: after `updateXMLDatastream` fails, the stored
  object still has the **old** RELS-EXT.
- Crash test: run a licence job over a tree of 10,000 objects in staging and kill the job JVM at random points 20 times. Afterwards
  every object has a RELS-EXT, either the old or the new one.
- Count FOXML saves per `updateXMLDatastream`: 1 after the fix, 2 today.

## Missing upstream

Reported (see Upstream issue). Still to do: a short comment on process-platform#14 pointing to kramerius#1371.

## Related

- [BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md): Akubra swallows storage errors on save and delete.
- [KB-002](KB-002-worker-loop-stops-on-poll-error.md), [KB-001](KB-001-process-gc-stops-forever.md): worker restarts are also
  where the process platform loses track of jobs.
