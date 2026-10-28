---
id: BUG-019
former_id: BUG-033
category: bug
title: FOXML import reports success after skipping unavailable directories
area: indexing
severity: medium
effort: XS
use_cases: [ingest]
review_ref: [H3]
upstream: null
touches: [kramerius/processes/import]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read Import at Kramerius 560676c; MZK process DB had no import jobs in 30 days"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-019 — FOXML import reports success after skipping unavailable directories

> **In one sentence:** A control-file import can skip a requested directory and still finish successfully.

## Symptom

An operator sees a finished import job although one or more listed folders were not processed; the only indication is a severe log line.

## Cause

`Import.java:268–278@560676c` logs a nonexistent or non-directory list entry and then uses `continue`. The method proceeds to its ordinary completion path (`Import.java:286@560676c`) without recording an incomplete result.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed in source at `560676c`; production incidence unmeasured. A 2026-10-28 read-only process DB aggregate found no import-named jobs in its 30-day grouping, so this window cannot establish incidence. The exact deployed image revision is unknown.

## Impact

Requested batches can be omitted with no process status that directs the operator to retry them.

## Fix

Validate all listed directories before ingesting any, and return a failed or warning job result that names the skipped entries in the private job log.

## Test

Use an isolated import-list fixture referring to one existing and one absent directory. Assert that the job reports incomplete input instead of full success.

## Related

[Bug hunt 2, H3](../raw/26-bug-hunt-2.md#candidates).
