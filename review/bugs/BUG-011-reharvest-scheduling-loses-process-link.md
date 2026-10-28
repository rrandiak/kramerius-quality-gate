---
id: BUG-011
former_id: BUG-037
category: bug
title: CDK reharvest scheduling can lose the process link after job creation
area: async
severity: high
effort: XL
use_cases: [admin, indexing]
review_ref: [H8]
upstream: null
touches: [kramerius/rest, process-platform/manager]
contracts: [process-scheduling-idempotency]
data_migration: false
checked: [source]
checked_how: "Read ReharvestResource and SolrReharvestManagerImpl at Kramerius 560676c; no production count"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-011 — CDK reharvest scheduling can lose the process link after job creation

> **In one sentence:** A reharvest process can start while its queue item lacks the process ID needed to track it.

## Symptom

The curator API reports a scheduling error after the process manager has accepted a job. The queue item may still say `scheduling` without a process link until a later worker update.

## Cause

`ReharvestResource.java:493–518@560676c` separately writes `scheduling`, creates the process, then writes its ID and `running` state. If the final queue update fails, `ReharvestResource.java:520–533@560676c` rolls back only when `scheduledProcessId == null`, so a successfully created process has no compensation or durable link. `SolrReharvestManagerImpl.java:72–85@560676c` logs update failures and returns null, which triggers this path.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source behavior at `560676c`; no production failure count. The CDK reharvest worker may later close the item, but that does not restore the missing process ID. The robust fix needs a shared scheduling idempotency contract across Kramerius and process-platform, so effort is XL.

## Impact

Operators cannot reliably associate the queue item with the running or failed job. An immediate retry sees `scheduling`; later retry logic can create duplicate work if no process link was stored.

## Fix

Use a durable scheduling intent with an idempotency key shared with process creation, then reconcile the returned process ID before marking the item running. On an uncertain result, query by that key rather than creating another job.

## Test

In an isolated fixture, accept process creation and fail the next queue-item update. Assert that the item retains a durable correlation key and a retry resolves to the original process.

## Related

[Bug hunt 2, H8](../raw/26-bug-hunt-2.md#candidates).
