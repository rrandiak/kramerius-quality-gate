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
upstream: https://github.com/ceskaexpedice/kramerius/issues/1382
touches: [kramerius/processes/import]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read Import at Kramerius 560676c; MZK process DB had no import jobs in 30 days"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-019 — FOXML import reports success after skipping unavailable directories

> **In one sentence:** A control-file import can skip a requested directory and still finish successfully.

## Upstream issue

[kramerius#1382](https://github.com/ceskaexpedice/kramerius/issues/1382) "Import skončí ako úspešný, aj keď preskočil adresár alebo nenaplánoval indexáciu",
opened by MZK on 2026-11-11 for BUG-008 and BUG-019 together: both places in `Import.run()` (skipped list entry with
`continue`, failed `scheduleSubProcess` caught as WARNING) at 7.2.2.4 (`3c8bacca`), same in 7.1.7 and `master`, a repro with
an import list naming a missing folder, since when (`d6d606c40`, 2012, `5.0.beta1`; `6ddca24ca`, 2017, `v6.0.0-alpha`) and
the fix (collect both kinds of failure, end with `WarningException`, schedule each object on its own). Code only: MZK's main
instance has run 3 imports, all clean.

## Symptom

An operator sees a finished import job although one or more listed folders were not processed; the only indication is a severe log line.

## Cause

`Import.java:268–278@560676c` logs a nonexistent or non-directory list entry and then uses `continue`. The method proceeds to its ordinary completion path (`Import.java:286@560676c`) without recording an incomplete result.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed in source at `560676c`; production incidence unmeasured. MZK's main instance (Kramerius 7.2.2.4) has run only 3 `import` jobs (all on 2026-05-25), and their logs are clean (all
roots scheduled, no skipped folder). The code is the same in 7.2.2.4 (`3c8bacca`), 7.1.7 and `master`. Not checked: the
NDK instance (7.1.7, ~29,600 imports since 2025-09, logs in the old `lp/` folders on `kramerius-0`).

## Impact

Requested batches can be omitted with no process status that directs the operator to retry them.

## Fix

Validate all listed directories before ingesting any, and return a failed or warning job result that names the skipped entries in the private job log.

## Test

Use an isolated import-list fixture referring to one existing and one absent directory. Assert that the job reports incomplete input instead of full success.

## Related

[Bug hunt 2, H3](../raw/26-bug-hunt-2.md#candidates).
