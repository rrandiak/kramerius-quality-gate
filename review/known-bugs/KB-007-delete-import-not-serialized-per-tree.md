---
id: KB-007
former_id: BUG-048
category: known-bug
title: Delete-tree and import jobs are not serialized for the same object tree
area: ingest
severity: high
effort: L
use_cases: [ingest, indexing, admin]
review_ref: [GH7]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1332
checked: [source, upstream-report]
checked_how: "Read DeleteTreeProcess and Import at Kramerius 560676c; incident in kramerius#1332; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-007 — Delete-tree and import jobs are not serialized for the same object tree

> **In one sentence:** overlapping ordinary delete and replacement-import jobs can leave a reimported tree incomplete or its search index inconsistent.

**GitHub issue verification:** this report checks [upstream issue #1332](https://github.com/ceskaexpedice/kramerius/issues/1332) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream issue reports orphaned pages and duplicate search documents when a replacement import overlaps deletion of the earlier tree.

## Cause

Kramerius `DeleteTreeProcess.java:102–115,190–201@560676c85d276bd53f2dbaae95e87ddc6abd6e07` discovers descendants, recursively deletes them, then deletes the current object, with no operation-wide tree lock or transaction. `Import.java:634–639@560676c85d276bd53f2dbaae95e87ddc6abd6e07` locks each imported PID while ingesting it, but this does not serialize the whole import with the delete-tree job. The two jobs can therefore interleave between objects; per-PID locks protect individual writes only.

## Evidence and frequency

The lack of tree-level serialization is confirmed at the pinned revision, and [upstream issue #1332](https://github.com/ceskaexpedice/kramerius/issues/1332) reports the resulting inconsistent state. This review did not inspect affected objects or count incidents at MZK.

## Impact

The repository and search index can disagree after replacement, requiring a repair or complete reindex. A later successful import does not necessarily remove stale search documents from a prior partial index path.

## Fix

Serialize delete and replacement import by the same stable root identity, with a lease long enough for the operation and a recovery path after worker loss. Reconcile stale search documents after replacement. Define the workflow contract so callers can await deletion completion before starting import.

## Test

Use an isolated repository and index fixture with a controlled scheduler to exercise overlapping jobs. Assert that the final tree and search documents match a single completed replacement, without using production traffic or a stress test.

## Related

- [GH7 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).
- [BUG-005](../bugs/BUG-005-delete-tree-ignores-child-failures.md) covers a separate incorrect job result after a failed descendant deletion.
