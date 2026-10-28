---
id: BUG-003
former_id: BUG-019
category: bug
title: The model-wide reindex reports a title as indexed even when some of its pages failed, and clears the title's "indexation in progress" marker
area: indexing
severity: high
effort: XS               # read the per-title Counters in NewIndexerProcessIndexModel and fail or report the title
use_cases: [indexing, search]
review_ref: [B15]
upstream: null
checked: [source]
checked_how: "Read the model-wide reindex at Kramerius 560676c; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-003 — The model-wide reindex reports a title as indexed even when some of its pages failed, and clears the title's "indexation in progress" marker

> **In one sentence:** the indexer catches every per-object error into a counter, and the model-wide reindex never looks at
> that counter, so a job that failed to index pages finishes as successful, its summary shows zero errors, and the titles
> with missing or stale pages are marked as fully indexed.

## Symptom

A model-wide reindex (`NewIndexerProcessIndexModel`) finishes with `Top-level objects erroneous: 0` and state FINISHED, while
the job log contains `Document error`, `I/O error`, `Solr error` or `Runtime error` lines for individual pages. Those pages
are missing from search or keep an old version.

## Cause

Kramerius `origin/master` `560676c`, module `processes/search-index`:

- `Indexer.indexObjectWithCounters` catches `DocumentException`, `IOException`, `SolrServerException`, `SolrException` and
  `RuntimeException` for each object, increments `counters.incrementErrors()` and returns normally
  (`indexer/execution/Indexer.java:326–340`; the same pattern at lines 585–589 and 638–645). `indexByObjectPid` then goes on to
  the children and returns normally too (lines 128–158).
- `indexByObjectPid` clears the title's "full indexation in progress" marker after the tree, whether or not objects in it
  failed (lines 141–143).
- `NewIndexerProcessIndexModel` creates a new `Counters` for every batch of 100 titles (`NewIndexerProcessIndexModel.java:116`),
  counts a title as indexed whenever `indexByObjectPid` returns (line 141), and counts errors only for exceptions that escape
  it (lines 142–146), which per-object errors never do. The `Counters` are never read, and the job fails only on those escaped
  exceptions or ignored titles (lines 161–163).
- The PID-list reindex (`NewIndexerProcessIndexObject`) does read its counters: it calls `indexer.summary(pids, counters)`
  (line 126), which throws when errors were counted (`Indexer.java:173–174`). Only the model-wide job is affected.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only; not yet counted at MZK. Since 2026-10-27 the indexing JVMs are traced (chart 1.3.2); an
`Indexer.indexObjectWithCounters` span with an error inside a model-wide job that finished OK confirms it.

## Impact

- Operators trust a model-wide reindex that left pages unindexed or stale; nothing tells them which titles to redo.
- The cleared marker hides the problem from any later check that looks for interrupted indexation.
- It combines with [BUG-013](BUG-013-ocr-dropped-on-invalid-xml-char.md) and Solr errors at peak times: the failures are real,
  they are just not reported.

## Fix

In `NewIndexerProcessIndexModel`, use one `Counters` per title (or compare `getErrors()` before and after each title); when a
title had errors, count it as erroneous, list it in the summary and do not clear its in-progress marker. Fail the job when any
title had errors, as the PID-list job already does.

## Test

- Unit test: a model-wide run over two titles where one page of the second throws `SolrServerException`; the summary must show
  one erroneous title, the job must fail, and the second title's in-progress marker must stay set.

## Related

- [PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md): batching changes where indexing errors surface; per-title
  error accounting is needed there too.
