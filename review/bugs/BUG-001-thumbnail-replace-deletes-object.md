---
id: BUG-001
former_id: BUG-017
category: bug
title: Setting a title's or collection's thumbnail deletes the whole object and ingests it again, so a failure in between loses the object
area: storage
severity: high
effort: XS               # replace IMG_THUMB in memory and save the object once instead of delete + ingest
use_cases: [admin, storage]
review_ref: [B20]
upstream: null
checked: [source]
checked_how: "Read ItemsResource.setImgThumb at Kramerius 560676c and Akubra 51d821b; not seen at MZK; unit test described, not run"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-001 — Setting a title's or collection's thumbnail deletes the whole object and ingests it again, so a failure in between loses the object

> **In one sentence:** the admin endpoint that copies a page's thumbnail to its title or collection rebuilds the target's
> FOXML in memory, then deletes the target object from the repository and ingests the rebuilt one, so a crash, a failed
> write or a failed processing-index update between the two leaves the title root or collection missing.

## Symptom

Only after a failure: the target object (a monograph, periodical, volume or collection) no longer exists in Akubra, while its
children still point to it; or it exists but the processing index has lost its relations to its children. The request may
have returned HTTP 200.

## Cause

Kramerius `origin/master` `560676c`, `rest/.../admin/v70/ItemsResource.java`, `setImgThumb`
(`PUT …/items/{pid}/streams/IMG_THUMB?srcPid=…`, lines 789–860):

- The target must not be a page (line 805), so it is a title root, a volume, an issue or a collection.
- Under the target's PID lock (lines 836–849) it reads the target FOXML, replaces the `IMG_THUMB` datastream element, and
  unmarshals the result, then calls `akubraRepository.delete(targetPid, false, false)` (line 845) and
  `akubraRepository.ingest(updatedDigitalObject)` (line 846).
- Akubra's `delete` removes the FOXML file, then the object's outgoing relations and its description from the processing
  index, and commits (`CoreRepositoryImpl.java:136–161`, akubra `51d821b`). `ingest` writes the object and rebuilds its
  processing-index entries (`CoreRepositoryImpl.java:103–112`), then commits (`AkubraRepositoryImpl.java:52–55`).
- Nothing makes the two steps one: if the JVM stops, the write fails, or the processing-index rebuild throws after the delete,
  the object is gone. A failed write is not even reported, because `AkubraDOManager.write` logs and swallows storage errors
  ([BUG-007](BUG-007-akubra-swallows-storage-errors.md)), so the endpoint returns 200 for an object that no longer exists.
- Between the delete and the ingest, the processing index has no outgoing relations for the target, so a title root briefly
  has no children for any concurrent reader or indexer.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only. Not observed at MZK. Every use of "set thumbnail from page" in the admin client runs this sequence.

## Impact

- Loss of a title root or collection object; its pages and children become orphans until it is restored from a backup or
  re-imported.
- Processing-index inconsistency even when nothing fails: a short window with no children for the target.

## Fix

Replace the datastream in place instead of deleting the object: under the lock, set the new `IMG_THUMB` datastream on the
loaded `DigitalObject` and save it once (the same single-save update that [KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md)
proposes for XML datastreams). The processing index does not change, since `IMG_THUMB` carries no relations.

## Test

- Unit test: with a repository mock whose `ingest` throws, `setImgThumb` must leave the target object in place, unchanged.
- Unit test: after a successful call, the target has the source's `IMG_THUMB` and the processing index still lists its children
  at every step.

## Related

- [KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md): the same two-step save pattern for datastream updates.
- [BUG-007](BUG-007-akubra-swallows-storage-errors.md): why the failed write goes unnoticed.
