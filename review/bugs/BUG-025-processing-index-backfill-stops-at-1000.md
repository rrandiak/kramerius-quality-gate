---
id: BUG-025
former_id: BUG-035
category: bug
title: Processing-index stream backfill stops after 1,000 relations
area: indexing
severity: medium
effort: S
use_cases: [ingest, indexing, storage]
review_ref: [H6]
upstream: null
touches: [akubra]
contracts: []
data_migration: false
checked: [source]
checked_how: "Read ProcessingIndexSolr at Akubra 51d821b; MZK relation fan-out not counted"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-025 — Processing-index stream backfill stops after 1,000 relations

> **In one sentence:** Updating a target description can leave incoming relation records without target stream metadata when more than 1,000 need backfill.

## Symptom

After a target description update, some relation records can still lack `targetPidStreams` even though the target has streams.

## Cause

`ProcessingIndexSolr.java:527–546@51d821b` queries relation records for a target with `setRows(1000)` and does not paginate. The description update creates atomic backfill documents only for that one result list (`ProcessingIndexSolr.java:569–578@51d821b`; equivalent path at lines 596–608).

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source defect at `51d821b`. MZK target fanout above this threshold and the exact deployed Akubra revision are unverified.

## Impact

Processing-index consumers may see incomplete target stream metadata after the update. A later update might backfill another page, but the first update does not complete the work.

## Fix

Page through all matching relation records with a stable cursor and enqueue updates for every identifier. Track completed pages and make retry safe.

## Test

Use an isolated Solr fixture with more than one page of incoming relation records lacking stream metadata. Assert that the update covers every record and that a retry leaves the same final state.

## Related

[Bug hunt 2, H6](../raw/26-bug-hunt-2.md#candidates).
