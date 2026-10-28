---
id: BUG-007
former_id: BUG-011
category: bug
title: Akubra logs and ignores failed saves and deletes, so callers and the processing index go on as if they succeeded
area: storage
severity: high
effort: S                # Akubra: rethrow from write/deleteStream/deleteObject; order deletes safely
use_cases: [ingest, admin, indexing, storage]
review_ref: [B9]           # flagged as a risk in review run 07, confirmed in source here
upstream: null
checked: [source]
checked_how: "Read CoreRepositoryImpl and AkubraDOManager at Akubra 51d821b; failure rate not known"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-007 — Akubra logs and ignores failed saves and deletes, so callers and the processing index go on as if they succeeded

> **In one sentence:** when writing an object to storage fails, or deleting it fails, Akubra only logs a SEVERE line and
> returns normally, so imports, licence jobs and curator edits report success, and the processing index is updated for a
> change that never reached storage.

## Symptom

A job finishes successfully, but the object in storage is unchanged, half-changed, or missing; the processing index (and later
the search index) disagrees with storage. The only trace is a log line such as:

```
SEVERE AkubraDOManager  Could not replace object in Akubra: <exception>
SEVERE AkubraDOManager  Could not remove object from Akubra: <exception>
SEVERE AkubraDOManager  Could not remove managed datastream from Akubra: <exception>
```

## Cause

`ceskaexpedice/akubra` at `51d821b`, `core/repository/impl/AkubraDOManager.java`:

| Method | What fails silently | Lines |
| --- | --- | --- |
| `write` (save object, used by ingest and every datastream create/update) | marshalling or `addOrReplaceObject`: caught as `Exception`, logged, method returns | 231–260 (catch 254–256) |
| `deleteStream` (remove a datastream) | saving the object without the datastream: caught, logged, returns | 189–215 (catch 210–212) |
| `deleteObject` | `storage.removeObject`: caught `LowlevelStorageException`, logged, returns | 172–187 (catch 182–184) |
| `removeManagedStream` | deleting a managed datastream file: caught, logged | 217–228 |

Two orderings make a failure worse than "nothing happened":

- `deleteObject` deletes the managed datastream **files first** (lines 174–178), then the object. If removing the object fails,
  the object stays with references to files that are gone.
- `deleteStream` deletes the managed datastream **file first** (line 197), then saves the object without it. If the save fails,
  the object still references a file that is gone.

What the callers do next, believing the call succeeded (`CoreRepositoryImpl.java`):

- `ingest` (lines 104–113): writes the object, then **rebuilds the processing index** for it. A failed write leaves an index entry
  for an object that is not in storage.
- `delete` (lines 136–160): deletes the object, then **deletes its processing index entries and commits**. A failed delete leaves
  an object in storage that the index no longer knows about.
- `createXMLDatastream` for RELS-EXT (lines 207–): writes, then rebuilds the object's relations in the processing index from the
  new RELS-EXT. A failed write leaves the index describing relations that are not stored.

**The processing index side fails silently too.** `core/processingindex/ProcessingIndexSolr.java` sends every write through a
`ConcurrentUpdateSolrClient` (`createProcessingUpdateClient`, line 658, queue of 100, SolrJ 8.8.1): document adds (lines 629,
644), the deletes by query (233–270), the rebuild batch (`req.process`, line 360) and the commit (510). This client only queues
the request and streams it to Solr from a background thread. If Solr rejects an update or the connection fails, the client calls
its `handleError(Throwable)`, which only logs through SLF4J; Akubra does not override it. The `try/catch` blocks around these calls
(e.g. `rebuildProcessingIndex`, lines 351–365) never see the failure, and the later `commit()` succeeds. So a rejected relation
or description document is lost without any error in the job, in either direction of the storage/index pair.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only; how often storage writes fail in production is not known. On NFS, failures come from stale file handles, quota or
space, permission changes and server restarts. With a network object store ([PH-004](../perf-hard/PH-004-s3-blob-store-under-akubra.md))
transient failures would be more common.

Since 2026-10-27 the job JVMs are traced with spans on Akubra calls (chart 1.3.2), but a swallowed exception does not mark the
span as an error, so this needs the log line: count "Could not replace object in Akubra" and "Could not remove object from Akubra"
in worker and curator logs.

## Impact

- Silent data loss or corruption: changes that users and jobs believe were saved are not.
- Storage and processing index drift apart without anyone noticing; repairing it needs a full processing index rebuild and a
  comparison with storage.
- Makes [KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md) worse: a failed second save in an update leaves the object without
  the datastream and the job does not notice.

## Fix

1. In `write`, `deleteStream` and `deleteObject`, rethrow storage failures as `RepositoryException` instead of logging and
   returning. `CoreRepositoryImpl` then skips the processing index update and the job fails visibly.
2. Change the order in deletes: save the object (or remove it) first, delete the managed datastream files after that succeeded. A
   leftover file is harmless; a reference to a missing file is not.
3. Keep logging, but at the point where the error is finally handled.
4. Make processing index writes report their failures: use a synchronous client (`HttpSolrClient`/`Http2SolrClient`, sending
   each rebuild as one batch, which `rebuildProcessingIndex` already builds), or override `handleError` to record the error and
   throw it from the next `commit()` or `blockUntilFinished()`.

## Test

- Unit tests with a storage stub that throws on `addOrReplaceObject` / `removeObject`: `ingest`, `delete`, `createXMLDatastream`
  and `deleteDatastream` throw, and the processing index is not changed.
- `deleteObject` with `removeObject` failing: managed datastream files still exist afterwards.
- Processing index against a Solr stub that answers 400 to updates: `rebuildProcessingIndex` (or the following commit) throws.

## Missing upstream

Not reported. An issue for `ceskaexpedice/akubra` should state:

- **Finding:** `AkubraDOManager.write`, `deleteStream` and `deleteObject` (`AkubraDOManager.java:172–260`) only log a
  storage failure ("Could not replace object in Akubra", "Could not remove object from Akubra") and return normally. The
  callers in `CoreRepositoryImpl` (ingest, delete, RELS-EXT write) then update the processing index as if the write had
  succeeded, and the import or job finishes successfully. `deleteObject` and `deleteStream` also delete managed datastream
  files before the object is saved or removed, so a failure leaves an object pointing to files that no longer exist.
- **Fix:** throw `RepositoryException` on storage failures, and delete datastream files only after the object write
  succeeded.

## Related

- [KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md): RELS-EXT updates save the object twice; this bug hides a failed second save.
- [PH-004](../perf-hard/PH-004-s3-blob-store-under-akubra.md): strict error propagation is a precondition for any network storage.
- [BUG-010](BUG-010-processing-index-submits-partial-rebuild.md): a failed processing-index rebuild still submits its partial batch and deletes the relations missing from it.
