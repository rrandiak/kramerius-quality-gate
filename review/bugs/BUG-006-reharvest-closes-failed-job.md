---
id: BUG-006
former_id: BUG-038
category: bug
title: CDK reharvest worker closes queue item after a failed job
area: async
severity: high
effort: XS
use_cases: [admin, indexing]
review_ref: [H9]
upstream: null
touches: [kramerius/processes/platform/cdk]
contracts: []
data_migration: false
checked: [source]
checked_how: "Read CDKReharvest and ReharvestUtils at Kramerius 560676c; no production count"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-006 — CDK reharvest worker closes queue item after a failed job

> **In one sentence:** A failed reharvest can be marked closed in the queue because close runs in `finally`.

## Symptom

The process job fails, but its queue item may be `closed` instead of showing unfinished work.

## Cause

`CDKReharvest.java:78–95@560676c` runs the main reharvest in a `try` and calls `ReharvestUtils.closeQueueItem` in `finally`, so both success and failure request the same queue transition. `ReharvestUtils.java:105–123@560676c` sets the item state to `closed`; if that write fails, it logs and returns normally.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source behavior at `560676c`; no production failure count. This applies after execution enters the worker's main `try` block. The queue's open-item lookup excludes `closed` records (`SolrReharvestManagerImpl.java:243–246@560676c`), and a test of the older reharvest path expects a queue item to stay unclosed on an unsuccessful branch (`KubernetesReharvestProcessTest.java:135–141@560676c`).

## Impact

An operator or scheduler using the queue state can miss a failed reharvest and leave source and destination indexes inconsistent.

## Fix

Move the `closed` transition after successful completion of the worker's main operation. A separate follow-up can introduce a distinct failed state and propagate queue-update failures.

## Test

In an isolated worker fixture, make the main operation fail and record queue updates with a fake client. Assert that the item remains recoverable and is never marked `closed` as successful work.

## Related

[Bug hunt 2, H9](../raw/26-bug-hunt-2.md#candidates).
