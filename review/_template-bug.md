---
id: BUG-000              # next free BUG- number; use _template-known-bug.md when an upstream issue exists
former_id: null
category: bug             # bug, or webclient-bug for kramerius-web-client defects (WC- prefix, webclient-bugs/)
title: Short description of the wrong behavior
area: async              # part of the code: async, caching, storage, indexing, search, …
severity: medium         # low | medium | high
effort: null             # XS | S | M | L | XL, see README.md#effort
touches: []              # modules or repositories changed
contracts: []            # api | solr-schema | storage-format | db-schema | config | logs-semantics
data_migration: false
use_cases: []            # image-open, search, indexing, ingest, admin, storage
review_ref: []           # review finding IDs, e.g. B13
upstream: null           # link to the issue once we open it
checked: []              # how the defect was confirmed: source | test | production | upstream-report
checked_how: ""          # one line: what was read, run or counted, at which revision; say if a test is written but not run
checked_on: null         # date of the last check
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-000 — Short description of the wrong behavior

> **In one sentence:** what goes wrong, for whom, and how often.

## Symptom

What a user, operator or log shows. Paste a shortened stack trace if there is one.

## Cause

The code that is wrong, with `File.java:line` on a named commit, and why it is wrong.

## Evidence and frequency

Production observation (ClickHouse query, time window, counts). If nothing beyond the code shows it, start with
**Known from code only; not confirmed by an MZK programmer and not seen in production.**

## Impact

Who is affected and what breaks: data, latency, availability, security.

## Fix

The smallest change that fixes it.

## Test

The fixture or scenario that fails before the fix and passes after it.

## Missing upstream

Not reported. What an issue in the right repository (`kramerius`, `akubra`, `process-platform`, …) should state, as
findings in English: the finding with `File.java:line` on a commit, and the fix. Name related upstream issues that do not
match exactly.

## Related

Other entries that touch the same code.
