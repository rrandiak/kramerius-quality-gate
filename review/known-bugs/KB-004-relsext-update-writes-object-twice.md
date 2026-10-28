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
upstream: "ceskaexpedice/process-platform#14"
checked: [source, upstream-report]
checked_how: "Read RELS-EXT update at Kramerius 560676c and Akubra 51d821b; incident reported in process-platform#14"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-004 — Updating RELS-EXT saves the object twice, first without RELS-EXT, so a crash in between deletes it for good

> **In one sentence:** Akubra updates an XML datastream by first saving the whole object without it and then saving the object
> again with the new version, so if the JVM dies or the second save fails between the two, the object stays in storage with
> no RELS-EXT, which is what happened at MZK when a worker restarted during a licence change.

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

Replace the datastream in memory and save the object once:

1. In `AkubraRepositoryImpl.updateXMLDatastream`, read the `DigitalObject`, replace the content of the datastream's version (or
   swap the `DatastreamType`), and call `manager.write` once. The single safe overwrite is then atomic: storage holds either the
   old or the new RELS-EXT, never none.
2. Apply the same to `updateManagedDatastream` and `updateExternalDatastream`. For managed datastreams, write the new file
   under a new version ID, save the FOXML pointing to it, and only then delete the old file.
3. Make the save throw on failure ([BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md)), so a failed update is a failed job, not a
   silent one.

## Test

- Unit test with a storage stub that throws on the second `addOrReplaceObject` call: after `updateXMLDatastream` fails, the stored
  object still has the **old** RELS-EXT.
- Crash test: run a licence job over a tree of 10,000 objects in staging and kill the job JVM at random points 20 times. Afterwards
  every object has a RELS-EXT, either the old or the new one.
- Count FOXML saves per `updateXMLDatastream`: 1 after the fix, 2 today.

## Missing upstream

[process-platform#14](https://github.com/ceskaexpedice/process-platform/issues/14) reports an object that lost RELS-EXT
while a licence job ran during a worker restart. The defect is in Akubra, so it may also deserve an issue in
`ceskaexpedice/akubra`. Missing there:

- **Cause:** `AkubraRepositoryImpl.updateXMLDatastream` (`AkubraRepositoryImpl.java:134–145`), which every RELS-EXT change
  goes through (`RelsExtHelperImpl.update`), saves the whole FOXML twice: `deleteDatastream` first saves the object
  **without** RELS-EXT (`AkubraDOManager.java:208`), then `createXMLDatastream` saves it again with the new RELS-EXT
  (`AkubraDOManager.java:253`). If the process dies in between, the object stays without RELS-EXT for good. If the second
  save fails, `AkubraDOManager.write` only logs it and returns normally ([BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md)).
- **Fix:** replace the datastream content in memory in `updateXMLDatastream` and save the object once. One save is atomic
  (safe overwrite), so storage always holds either the old or the new RELS-EXT. `write` should throw on failure.

## Related

- [BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md): Akubra swallows storage errors on save and delete.
- [KB-002](KB-002-worker-loop-stops-on-poll-error.md), [KB-001](KB-001-process-gc-stops-forever.md): worker restarts are also
  where the process platform loses track of jobs.
