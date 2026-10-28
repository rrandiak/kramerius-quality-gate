---
id: BUG-016
former_id: BUG-016
category: bug
title: Exporting an object fails to include managed datastreams referenced by a file URL, even when the file exists
area: storage
severity: medium
effort: XS               # resolveArchiveManagedStream: resolve by contentLocation TYPE, as the read path does
use_cases: [admin, storage]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read the export at Akubra 51d821b; 7 days of MZK curator logs (110 errors) and one export of 52 titles"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-016 — Exporting an object fails to include managed datastreams referenced by a file URL, even when the file exists

> **In one sentence:** Akubra's export looks up every managed datastream in its internal datastream store, so a datastream
> stored as a `file:` URL reference is never read, even though the file exists and normal reads serve it; the export logs
> an error and returns FOXML that still points to the file.

## Symptom

Exporting an affected object (admin `GET /search/api/admin/v7.0/repository/export`) logs, once per such datastream:

```
SEVERE AkubraDOManager  Could not resolve archive managed datastream:
    java.lang.IllegalArgumentException: Malformed object token: file:/kramerius_ndk/import/…
```

and returns FOXML in which `ALTO` and `TEXT_OCR` are still `CONTROL_GROUP="M"` with
`<contentLocation TYPE="URL" REF="file:/kramerius_ndk/import/…"/>` instead of their content. Reading the same datastream
through the API works.

## Cause

Akubra `51d821b`:

- `AkubraRepositoryImpl.export` calls `coreRepository.resolveArchivedDatastreams(digitalObject)`
  (`AkubraRepositoryImpl.java:73–79`).
- `AkubraDOManager.resolveArchiveManagedStream` takes every `M` datastream version and calls
  `retrieveDatastream(contentLocation.getREF())` on the internal datastream store, without looking at the location `TYPE`
  (`AkubraDOManager.java:368–380`).
- For a `TYPE="URL"` reference the `REF` is a `file:` URL, not an internal key, so the store rejects it before touching the
  disk (`AkubraLowlevelStorage.getBlobId`, `AkubraLowlevelStorage.java:578–596`). The exception is caught, logged, and the
  version keeps its reference.
- The read path resolves the same reference correctly: `RepositoryUtils.getDatastreamContent` reads internal IDs from the
  store, local Fedora references by key, and other URLs with `readFromURL` (`RepositoryUtils.java:132–148`).

## Evidence and frequency

Seen at MZK on 2026-10-27/28: 110 such `SEVERE` lines in 7 days of curator logs, all from an export of 52 titles. In that
export, 55 objects of one title had ALTO and TEXT_OCR left as `file:` references; their files were present in the import
folder at the time.

## Impact

- Exports of these objects are incomplete without failing: a backup, migration or transfer built on export gets references to
  paths that only exist on the source machine.
- Anyone using export to repair or move such objects (for example to copy the files into the repository) cannot rely on it.

## Fix

In `resolveArchiveManagedStream`, resolve each version by its `contentLocation` type, reusing the read-path logic:
`INTERNAL_ID` from the datastream store, local references by key, `URL` with `readFromURL`. If a version cannot be resolved,
fail the export with the PID and datastream ID instead of returning a partial object.

## Test

- Unit test: an object whose ALTO is `CONTROL_GROUP="M"` with `<contentLocation TYPE="URL" REF="file:/tmp/x.xml"/>` and the
  file present; the export must contain the file's content as `binaryContent` and no `contentLocation`.
- Unit test: the same with the file missing; the export must fail and name the PID and datastream.

## Related

- [KB-012](../known-bugs/KB-012-internalize-file-referenced-streams.md): copying such files into Akubra on ingest, so the
  references stop existing.
- [BUG-007](BUG-007-akubra-swallows-storage-errors.md): the same "log and continue" pattern in Akubra's storage code.
