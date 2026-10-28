---
id: PM-000               # PS- | PM- | PH- by effort, next free number in that category
former_id: null
category: perf-medium    # perf-simple (XS–S) | perf-medium (M) | perf-hard (L–XL), see README.md#categories
title: Short imperative title
area: caching            # part of the code: async, caching, storage, indexing, search, …
impact: unknown          # low | medium | high | unknown
effort: null             # XS | S | M | L | XL, see README.md#effort
touches: []              # modules or repositories changed
contracts: []            # api | solr-schema | storage-format | db-schema | config | logs-semantics
data_migration: false
use_cases: []            # image-open, search, indexing, ingest, admin, storage
review: []               # review/ reports this entry is built on
upstream: null           # upstream issue or PR link, if any
---

# PM-000 — Short imperative title

> **In one sentence:** what we would change and what it saves.

## Today

How it works now. Name the code paths with `File.java:line` on a named commit and link the evidence in `review/raw/`.
Say what was observed in production and what was only read in source.

## Idea

What changes. Add a Mermaid diagram if the flow is not obvious.

## Expected gain

| Use case | Today | After (rough) | Confidence | Basis |
| --- | --- | --- | --- | --- |
| image-open | p95 ? ms | ? | low | hypothesis / source / ClickHouse / benchmark |

Gains from different entries may overlap. Say which other entries remove the same cost.

## Pros

-

## Cons and risks

-

## Alternatives

1. **Do nothing.** What it costs us to keep the current behavior.
2.

## Effort

**Size: ?**, set by the highest criterion met (see [effort scale](README.md#effort)).

| Part | Size | Why this size |
| --- | --- | --- |
|  |  |  |

Dependencies on other entries, fixes or decisions.

## How we would validate it

The measurement, benchmark or ClickHouse query that would confirm or reject the idea,
and the result that would make us drop it.

## Open questions

-
