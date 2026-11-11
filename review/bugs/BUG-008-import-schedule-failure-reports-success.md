---
id: BUG-008
former_id: BUG-031
category: bug
title: FOXML import reports success after child indexing cannot be scheduled
area: indexing
severity: high
effort: S
use_cases: [ingest, indexing]
review_ref: [H1]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1382
touches: [kramerius/processes/import]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read Import at Kramerius 560676c and ManagerClient at process-platform 976dc4b; MZK process DB had no import jobs in 30 days"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-008 — FOXML import reports success after child indexing cannot be scheduled

> **In one sentence:** A failed sub-process scheduling call can leave newly ingested objects out of search while the import job finishes successfully.

## Upstream issue

[kramerius#1382](https://github.com/ceskaexpedice/kramerius/issues/1382) "Import skončí ako úspešný, aj keď preskočil adresár alebo nenaplánoval indexáciu",
opened by MZK on 2026-11-11 for BUG-008 and BUG-019 together: both places in `Import.run()` (skipped list entry with
`continue`, failed `scheduleSubProcess` caught as WARNING) at 7.2.2.4 (`3c8bacca`), same in 7.1.7 and `master`, a repro with
an import list naming a missing folder, since when (`d6d606c40`, 2012, `5.0.beta1`; `6ddca24ca`, 2017, `v6.0.0-alpha`) and
the fix (collect both kinds of failure, end with `WarningException`, schedule each object on its own). Code only: MZK's main
instance has run 3 imports, all clean.

## Symptom

An import can complete without all expected indexing child jobs. The worker logs a warning, but the process method returns normally.

## Cause

`Import.java:443–452@560676c` catches a scheduling exception for root objects, logs it and continues to the method's normal return. Equivalent catch blocks surround collection and convolute scheduling at `Import.java:324–346,353–423@560676c`. The process-platform client throws on a non-success manager response or transport error (`ManagerClient.java:151–159@976dc4b`), so this catch can hide a real failed submission.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed in source at the named revisions; production incidence unmeasured. MZK's main instance (Kramerius 7.2.2.4) has run only 3 `import` jobs (all on 2026-05-25), and their logs are clean (all
roots scheduled, no skipped folder). The code is the same in 7.2.2.4 (`3c8bacca`), 7.1.7 and `master`. Not checked: the
NDK instance (7.1.7, ~29,600 imports since 2025-09, logs in the old `lp/` folders on `kramerius-0`).

## Impact

Objects exist in the repository but can remain absent or stale in search. Items after the failed child in the same loop are not submitted.

## Fix

Track each planned child and propagate incomplete scheduling as a failed or warning import result. Make retries submit only missing children with a stable idempotency key.

## Test

Use an in-memory scheduler stub that fails one of several child submissions. Assert that the import does not report full success and identifies the unscheduled children.

## Related

[Bug hunt 2, H1](../raw/26-bug-hunt-2.md#candidates). This is separate from BUG-003, which hides errors *inside* an already scheduled model reindex.
