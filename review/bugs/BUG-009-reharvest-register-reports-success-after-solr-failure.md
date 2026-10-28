---
id: BUG-009
former_id: BUG-039
category: bug
title: CDK reharvest registration reports success after a Solr write failure
area: async
severity: high
effort: S
use_cases: [admin, indexing]
review_ref: [H10]
upstream: null
touches: [kramerius/rest]
contracts: []
data_migration: false
checked: [source]
checked_how: "Read SolrReharvestManagerImpl and ReharvestResource at Kramerius 560676c; no production count"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-009 — CDK reharvest registration reports success after a Solr write failure

> **In one sentence:** The curator API can return 200 for a reharvest request that was not registered in the queue.

## Symptom

A curator sees successful registration, but the requested queue item may be absent after a Solr write failure.

## Cause

`SolrReharvestManagerImpl.java:53–68@560676c` catches and logs `UniformInterfaceException` and `ClientHandlerException` from the Solr registration request, then returns normally. `ReharvestResource.java:360–377@560676c` calls this void method and immediately returns 200 in the reviewed registration branches. No success result or queue readback reaches the API handler.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source behavior at `560676c`; no production failure count. This is distinct from the later process-scheduling gap in BUG-011.

## Impact

Requested reharvest work can be omitted while the API tells the curator it was accepted. There is no failed item to retry through the queue.

## Fix

Propagate Solr registration failures to the API and return a non-success response. Verify the created item by its ID or use an acknowledged write result before reporting success.

## Test

Use an isolated resource fixture whose queue client reports a registration failure. Assert the API does not return 200 and no success body is emitted.

## Related

[Bug hunt 2, H10](../raw/26-bug-hunt-2.md#candidates).
