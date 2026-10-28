---
id: BUG-024
former_id: BUG-032
category: bug
title: FOXML merge ignores failed relation writes
area: storage
severity: medium
effort: S
use_cases: [ingest, storage]
review_ref: [H2]
upstream: null
touches: [kramerius/processes/import]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read Import.merge at Kramerius 560676c; MZK process DB had no import jobs in 30 days"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-024 — FOXML merge ignores failed relation writes

> **In one sentence:** A merge can omit some imported relationships yet return as though it succeeded.

## Symptom

The import log may contain a failed-relation message even though the merge continues and the job finishes.

## Cause

`Import.java:725–741@560676c` writes each newly imported relationship separately. Its `catch (Exception)` at line 736 logs a failed write and continues; the returned `touched` flag reflects any earlier success, not whether all writes succeeded.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed in source at `560676c`; production incidence unmeasured. A 2026-10-28 read-only process DB aggregate found no import-named jobs in its 30-day grouping, so this window cannot establish incidence. The exact deployed image revision is unknown.

## Impact

Repository relationships can be incomplete without a job result that prompts repair. Search and rights metadata derived from those relationships may consequently remain stale until a successful retry.

## Fix

Collect failed relation writes and fail the merge if any remain. Make reruns idempotent by checking already present relations before writing.

## Test

Use an in-memory repository stub that accepts one relation and fails the next. Assert the caller receives an incomplete-merge result rather than success.

## Related

[Bug hunt 2, H2](../raw/26-bug-hunt-2.md#candidates).
