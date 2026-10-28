---
id: QOL-000              # next free QOL- number; levels of one entry as QOL-000.1, QOL-000.2, …
former_id: null
category: quality-of-life
title: Short imperative title
area: operations         # part of the code: modularization, operations, communication, …
impact: unknown          # low | medium | high | unknown
effort: null             # XS | S | M | L | XL, see README.md#effort
touches: []              # modules or repositories changed
contracts: []            # api | solr-schema | storage-format | db-schema | config | logs-semantics
data_migration: false
use_cases: []            # image-open, search, indexing, ingest, admin, storage
review: []               # review/ reports this entry is built on
upstream: null           # upstream issue or PR link, if any
---

# QOL-000 — Short imperative title

> **In one sentence:** what we would change and who it makes life easier for.

## Today

How it works now and what is hard about it, for whom (developers, operators, curators, other libraries). Name the code
with `File.java:line` on a named commit and link the evidence in `review/raw/`. Separate what was measured from what was read.

## Questions and answers

The decisions this entry makes. One subsection per question, so a reader can follow the reasoning and disagree with a
specific step.

### Q1. The question, as someone would ask it

| Option | For | Against |
| --- | --- | --- |
| A |  |  |
| B |  |  |

**Answer:** the chosen option, in one sentence.
**Why:** the deciding facts, with evidence (source line, measurement, review report).

## Proposal

What changes, in the order it would be done. For a large entry, split it into levels that are each useful on their own:

| Level | Entry | What changes | Effort | Needs |
| --- | --- | --- | --- | --- |
| 1 | QOL-000.1 |  |  | nothing |

## What gets easier

| Who | Today | After | Basis |
| --- | --- | --- | --- |
| developers |  |  | source / measurement / packaging |

Say also what does **not** change (e.g. request latency), so nobody expects a speed gain from it.

## Costs and risks

-

## Alternatives

1. **Do nothing.** What it costs us to keep things as they are.
2.

## Effort

**Size: ?**, set by the highest criterion met (see [effort scale](README.md#effort)).

| Part | Size | Why this size |
| --- | --- | --- |
|  |  |  |

## How we know it worked

Checks that can fail: a test, a build rule, a count, a time to set something up.

## Open questions

-
