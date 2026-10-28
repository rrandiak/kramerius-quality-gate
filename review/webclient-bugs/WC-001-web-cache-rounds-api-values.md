---
id: WC-001
former_id: BUG-036
category: webclient-bug
title: Web client cache rounds numbers in large API responses
area: caching
severity: medium
effort: XS
use_cases: [search, image-open, admin]
review_ref: [H7]
upstream: null
touches: [kramerius-web-client-v3]
contracts: []
data_migration: false
checked: [source]
checked_how: "Read the web client cache interceptor at kramerius-web-client 967fa034; deployed bundle revision not checked"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# WC-001 — Web client cache rounds numbers in large API responses

> **In one sentence:** The browser can return changed numeric API values from its persistent GET cache after the first request.

## Symptom

The first GET returns the server value, while a later cache hit can return the same response with fractional values rounded to two decimal places.

## Cause

`simple-cache.interceptor-fn.ts:39–59@967fa034` serializes responses of at least 5,000 characters with a replacer that rounds every non-integer number. If this shorter JSON is marked `compressed`, the interceptor stores it (`simple-cache.interceptor-fn.ts:143–167@967fa034`) and parses it back on a hit (`simple-cache.interceptor-fn.ts:98–125@967fa034`). Rounding changes data; it is not lossless compression.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Confirmed conditional source defect at `967fa034`. The affected response fields and deployed client revision are unverified; no production response bodies were inspected.

## Impact

Numeric coordinates, measurements, or other fractional fields in a sufficiently large cacheable response can be changed for later reads in the same browser.

## Fix

Store the original serialized response without a numeric replacer, or use a lossless compression algorithm. Invalidate existing cache entries written by the old format.

## Test

Use an in-memory interceptor fixture with a large response containing a fractional field. Assert that the first response and the cache hit preserve the exact same value.

## Related

[Bug hunt 2, H7](../raw/26-bug-hunt-2.md#candidates).
