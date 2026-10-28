---
id: BUG-010
former_id: BUG-040
category: bug
title: Processing-index rebuild submits partial relations after an error
area: storage
severity: high
effort: S
use_cases: [admin, indexing, storage]
review_ref: [H11]
upstream: null
touches: [akubra/processing-index, akubra/repository]
contracts: []
data_migration: false
checked: [source]
checked_how: "Read ProcessingIndexSolr and CoreRepositoryImpl at Akubra 51d821b; no production count"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-010 — Processing-index rebuild submits partial relations after an error

> **In one sentence:** A failed RELS-EXT rebuild can publish a partial relation set and still return a successful repository write.

## Symptom

After a RELS-EXT update, the processing index can lack relations present in the repository while the write caller sees success.

## Cause

`ProcessingIndexSolr.java:332–365@51d821b` accumulates relation documents and submits a nonempty batch in `finally`, even when the rebuild throws. `CoreRepositoryImpl.java:215–243@51d821b` customizes that same request by deleting old relation IDs absent from the batch. Its catch logs the rebuild failure, then returns the datastream (`CoreRepositoryImpl.java:244–248@51d821b`). A partial batch can therefore both add only some new relations and remove old ones.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source behavior at `51d821b`; production incidence unknown. This is a partial-batch publication path, distinct from BUG-007's swallowed storage and Solr transport errors.

## Impact

Repository and processing-index relation sets can diverge. Consumers relying on the processing index may miss relationships until a successful reconciliation rebuild.

## Fix

Build the complete update request before submitting it; do not submit in `finally`. Propagate rebuild failures to the repository caller and arrange reconciliation when the repository write has already succeeded.

## Test

Use an in-memory rebuild fixture that prepares one relation and then fails during a later step. Assert that no partial Solr update is submitted and the caller sees a failed or explicitly partial result.

## Related

[Bug hunt 2, H11](../raw/26-bug-hunt-2.md#candidates); [BUG-007](BUG-007-akubra-swallows-storage-errors.md).
