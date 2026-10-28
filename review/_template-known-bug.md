---
id: KB-000               # next free KB- number
former_id: null
category: known-bug
title: Short description of the wrong behavior
area: async              # part of the code: async, caching, storage, indexing, search, …
severity: medium         # low | medium | high
effort: null             # XS | S | M | L | XL, see README.md#effort
touches: []              # modules or repositories changed
contracts: []            # api | solr-schema | storage-format | db-schema | config | logs-semantics
data_migration: false
use_cases: []            # image-open, search, indexing, ingest, admin, storage
review_ref: []           # review finding IDs, e.g. B13
upstream: null           # required: the existing issue, e.g. https://github.com/ceskaexpedice/kramerius/issues/1300
checked: []              # how the defect was confirmed: source | test | production | upstream-report
checked_how: ""          # one line: what was read, run or counted, at which revision; say if a test is written but not run
checked_on: null         # date of the last check
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-000 — Short description of the wrong behavior

> **In one sentence:** what goes wrong, and what this entry adds to the upstream issue.

## Upstream issue

| | |
| --- | --- |
| Issue | link, open or closed, reported by which institution and when |
| What it reports | the symptom in the issue's own terms |
| Match | exact / same mechanism / subset (say which part this entry covers beyond it) |
| What we add | cause, fix, production counts, a second path, a test |

## Symptom

What a user, operator or log shows, if it differs from or extends the issue.

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

What the upstream issue does not have yet, stated as findings in English, not as a comment to paste: the cause with
`File.java:line` on a commit, production counts, a second path, the fix. No internal hostnames, no personal data,
nothing from held-back topics.

## Related

Other entries that touch the same code.
