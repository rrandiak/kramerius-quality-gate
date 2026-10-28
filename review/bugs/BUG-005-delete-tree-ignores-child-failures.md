---
id: BUG-005
former_id: BUG-034
category: bug
title: Delete-tree job ignores failed descendants in its result
area: storage
severity: high
effort: XS
use_cases: [admin, storage]
review_ref: [H4]
upstream: null
touches: [kramerius/processes/dnntflag]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read DeleteTreeProcess at Kramerius 560676c; MZK process DB 30-day status counts (cannot show the hidden failure)"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-005 — Delete-tree job ignores failed descendants in its result

> **In one sentence:** A delete-tree job can report success even when a descendant deletion returned failure.

## Symptom

The job can finish without a warning while a child object was not fully deleted in inconsistency-tolerant mode.

## Cause

`DeleteTreeProcess.java:104–114@560676c` initializes `someProblem` to false and then uses `someProblem &= deleteTree(child, ...)`. Bitwise AND evaluates the child call but leaves false unchanged, so failed child returns are lost. The method returns `!someProblem` at line 201, and the top-level `deleteMain` raises a warning only when that result is false (`DeleteTreeProcess.java:92–96@560676c`).

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed in source at `560676c`; failure incidence unmeasured. MZK's read-only process DB aggregate counted 68 FINISHED and one FAILED `delete-tree` job in the 30 days before 2026-10-28. These status totals establish plugin use but cannot reveal a descendant error hidden inside a FINISHED job.

## Impact

Operators can treat a partial deletion as complete. Repository and search-index remnants may need manual reconciliation.

## Fix

Replace the accumulation with `someProblem |= !deleteTree(child, ...)` so every child is evaluated and any false result is retained.

## Test

Use an isolated recursive deletion fixture whose child returns false and whose root has no local failure. Assert that the top-level result is a warning.

## Related

[Bug hunt 2, H4](../raw/26-bug-hunt-2.md#candidates).
