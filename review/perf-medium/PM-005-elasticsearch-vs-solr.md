---
id: PM-005
former_id: IDEA-009
category: perf-medium
title: Keep Solr for now; fix how Kramerius uses it, and make the search API engine-neutral before any switch
area: search
impact: medium           # the engine is not the bottleneck; the API contract is the real lock-in
effort: XL               # a switch means every Solr use, the public API and CDK harvesting
touches: [kramerius rest (search API), shared statistics, processing index, CDK processes, kramerius-helm-chart, web clients]
contracts: [api, solr-schema]
data_migration: true     # full reindex into a new engine
use_cases: [search, indexing, image-open, admin]
review: [08-search-engine-options, 12-search-400-correlation, 05-read-index-capacity]
---

# PM-005 — Keep Solr for now; fix how Kramerius uses it, and make the search API engine-neutral before any switch

> **In one sentence:** Solr and Elasticsearch run the same Lucene engine, so a switch would not make searching faster by
> itself; what makes a switch hard is that Kramerius exposes Solr's query language and response format as its public API and
> that the CDK harvests libraries over the Solr protocol, so the useful step now is to fix how Kramerius uses Solr and to
> decouple the API from it.

## Today

**Where Solr is used** (Kramerius `origin/master` `560676c`, chart `solrConfig`): seven endpoints, not one.

| Use | What it holds | Notes |
| --- | --- | --- |
| `search` | public search index | the one people think of |
| `processing` | relations between objects (the processing index) | Akubra and every import and reindex depend on it |
| `logs` | statistics (access log records) | written per `info.json` ([PM-003](PM-003-batched-access-log-writer.md), [KB-003](../known-bugs/KB-003-cdk-probes-info-json-per-tile.md)) |
| `sdnnt`, `monitor` | SDNNT sync, API monitor | |
| `updates`, `reharvest` | CDK only | |

30 Java files import SolrJ.

**Solr is the public API.** `GET /search/api/client/v7.0/search` passes the client's `q`, `fq`, `fl`, `sort`, facet and highlight
parameters to Solr `/select` and returns Solr's JSON or XML with some post-processing (`SearchResource.java:148–309`); `/terms`
does the same for the terms component (lines 526–560). The web client (digitalniknihovna.cz), the CDK and libraries' own
tools all send Solr syntax.

**The CDK harvests over Solr.** `CDKCopyMigrationIndexFeeder` queries a source library with `q=pid:(…)&fl=…&wt=xml` and sends Solr XML
update batches to the CDK index (lines 83–132, 217–221). A library that changes engine breaks CDK harvesting unless it keeps a
Solr-compatible endpoint.

**What production shows** (MZK, [run 01](../raw/01-baseline.md), 2026-10-19): 377,902 client searches a day, p50 22 ms,
p95 421 ms, p99 1,926 ms, 1,657 HTTP 5xx. Two failure peaks were traced to Solr answering HTTP 400 and Kramerius mapping that to
5xx ([run 12](../raw/12-search-400-correlation.md)); why Solr rejected those queries is still unknown, but a rejected query
is not an engine capacity limit. Indexing costs come from
how Kramerius writes (one document per request, per-title commits, [PM-004](PM-004-batch-solr-writes-in-indexer.md)).

## Elasticsearch versus Solr (note 10)

Migration of code and data is left out here, as asked. Both are built on Lucene: same inverted index, same BM25 scoring, same
analysis building blocks, so per-query speed on equal hardware and equal schema is similar.

| Topic | Solr | Elasticsearch |
| --- | --- | --- |
| Query features | standard, edismax, local params, facets, terms, highlighting | query DSL and query-string, aggregations (richer: nested, pipeline), highlighting |
| Facet counts | exact on one shard; distributed counts can be refined | terms aggregations can be approximate across shards unless tuned |
| Czech analysis | Hunspell, stopwords, folding, synonyms (in use) | same building blocks (Hunspell, synonyms); chains must be rebuilt and verified |
| Writes and visibility | update handler, `commitWithin`, soft and hard commits, atomic updates | bulk API, `refresh_interval`, partial updates; same Lucene segment model |
| Cluster coordination | SolrCloud needs **ZooKeeper** (an extra system to run); standalone Solr does not, but has no automatic failover | built-in coordination, no ZooKeeper |
| Operations tooling | Admin UI, metrics; Kibana-like tooling is not built in | Kibana, snapshot lifecycle, index lifecycle management; some features are paid tiers |
| Licence | Apache 2.0 | AGPL, SSPL or Elastic License; **OpenSearch** is the Apache 2.0 fork |
| Team knowledge | everything in Kramerius, CDK and the libraries is Solr-based | new |

**Pros of Elasticsearch:** no ZooKeeper, a stronger aggregation framework, better day-to-day tooling (Kibana, index lifecycle),
a cleaner bulk and refresh model, managed offerings.
**Cons:** not faster per query, approximate distributed facet counts unless tuned, a licence that is not Apache 2.0 (or use
OpenSearch), a second operating model next to Solr for every library and the CDK, and paid tiers for some security and lifecycle
features.

## Idea

Do not switch now. Instead:

1. **Fix how Kramerius uses Solr** where production shows cost: batched writes and no per-title commit
   ([PM-004](PM-004-batch-solr-writes-in-indexer.md)), fewer repeated Solr reads in rights checks
   ([PS-002](../perf-simple/PS-002-rights-check-refetches-solr-doc.md)), finding why Solr answers HTTP 400 at peaks ([run 12](../raw/12-search-400-correlation.md)),
   and statistics writes off the request path ([PM-003](PM-003-batched-access-log-writer.md)).
2. **Make the public search API engine-neutral** over time: a documented Kramerius query model (fields, filters, facets, paging,
   highlighting) that `SearchResource` translates to Solr. New clients use it; the Solr pass-through stays for existing clients
   with a deprecation period. This is what any later engine change would need first, and it also makes the API safer (no
   arbitrary Solr parameters from the internet).
3. **Decide per use, not "Solr vs Elasticsearch" for everything.** The statistics `logs` core is the most natural candidate for
   another store (it is an append-only event log; ClickHouse or Elasticsearch suit it better than a search index), and it is not
   part of the public search contract.
4. Revisit the engine question only with a measured reason (ZooKeeper operations pain, an aggregation the API needs, or a
   measured capacity limit after steps 1–2).

## Expected gain

| Use case | Today | After (rough) | Confidence | Basis |
| --- | --- | --- | --- | --- |
| search p95/p99 from switching engine alone | p95 421 ms, p99 1.9 s | about the same | medium | same Lucene engine; no measurement |
| search errors (HTTP 400 peaks) | 1,657 5xx / day on 2026-10-19 | lower once the 400 cause is found and fixed | low | run 12 traces |
| indexing throughput | one add per page, per-title commits | higher with PM-004 | low | source; not yet measured |
| operating cost | Solr (+ ZooKeeper where SolrCloud is used) per library | unchanged now | — | — |

## Pros

- Spends effort where production shows cost, not on a migration with no speed gain.
- An engine-neutral API removes the hardest part of any future switch and stops exposing raw Solr parameters publicly.
- Keeps CDK harvesting and other libraries working unchanged.

## Cons and risks

- Keeps ZooKeeper and Solr operations as they are.
- A new query model is API work: it must cover what the web clients do today, and the pass-through must live on for a while.
- If a library or the CDK decides to move anyway, Kramerius will not be ready for it without step 2.

## Alternatives

1. **Switch to Elasticsearch (or OpenSearch) now.** XL: every Solr use, a translation of Solr query syntax for all clients, a new
   CDK harvesting protocol, coordination with all libraries and the CDK, full reindex. No measured speed gain to justify it.
2. **Elasticsearch only for statistics** (`logs`). Small and independent; but ClickHouse is already deployed for telemetry and fits
   an event log at least as well.
3. **Do nothing.** Solr usage problems (HTTP 400s, write pattern) stay.

## Effort

**Size: XL for a switch; M for the recommended steps.**

| Part | Size | Why this size |
| --- | --- | --- |
| Step 1: fixes in Solr usage | S–M each | see PM-004, PS-002, PM-003, run 12 |
| Step 2: engine-neutral search API with pass-through kept | L | REST API contract change, clients migrate over time |
| Step 3: statistics to another store | M | one writer and the statistics reports |
| A full switch to Elasticsearch | XL | all seven Solr uses, API, CDK protocol, every library, reindex |

## How we would validate it

1. Before any engine work: from the `kramerius-public` traces, break search time into Kramerius code, Solr time and response
   post-processing; classify the HTTP 400 queries by shape. If Solr time is not the main part of p95/p99, the engine is not the problem.
2. If an engine comparison is still wanted: one isolated collection, a fixed document set with Czech OCR, and golden queries
   (exact PID, Czech full text, filtered facets, OCR highlights). Compare results and facet counts first, then latency at equal
   hardware ([run 08](../raw/08-search-engine-options.md) has the full plan).

## Open questions

- Is anyone (another library, the CDK team) already planning to move away from Solr, or to OpenSearch?
- Which Solr parameters do the web clients actually send? A sample of query shapes would size step 2.
- Does MZK (and do other libraries) run SolrCloud with ZooKeeper or standalone Solr, and is it causing operational pain? That is
  the strongest operational argument for a switch.
