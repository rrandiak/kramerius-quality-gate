---
id: KB-009
former_id: BUG-043
category: known-bug
title: Zero-count child stream facets set OCR and ALTO flags to true
area: indexing
severity: medium
effort: XS
use_cases: [search, indexing]
review_ref: [GH2]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1356
checked: [source, upstream-report]
checked_how: "Read ProcessingIndexSolr at Akubra 51d821b and SolrInputBuilder at Kramerius 560676c; kramerius#1356; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-009 — Zero-count child stream facets set OCR and ALTO flags to true

> **In one sentence:** search can claim a title has OCR or ALTO even when none of its pages has that stream.

**GitHub issue verification:** this report checks [upstream issue #1356](https://github.com/ceskaexpedice/kramerius/issues/1356) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream report observes `has_text_ocr_content` and `has_alto_content` set to true on titles without those streams.

## Cause

Akubra `ProcessingIndexSolr.java:297–310@51d821bcb55b89050e834ea00651aeb051146495` requests a `targetPidStreams` facet and appends every returned term name without checking its count or setting a positive minimum count. [Solr's field-facet default minimum count is zero](https://solr.apache.org/guide/solr/9_8/query-guide/faceting.html), so zero-count terms can appear. Kramerius `SolrInputBuilder.java:751–764@560676c85d276bd53f2dbaae95e87ddc6abd6e07` treats the presence of the `OCR_TEXT` or `OCR_ALTO` name as proof that a child has that stream. A zero-count facet term therefore becomes a false true flag.

## Evidence and frequency

The code path is confirmed at both pinned revisions. [Upstream issue #1356](https://github.com/ceskaexpedice/kramerius/issues/1356) reports false flags in two libraries; this review has not counted MZK documents independently.

## Impact

Search filters for OCR and ALTO availability return titles that have neither, so readers and operators cannot reliably find documents missing text layers.

## Fix

Set a positive facet minimum count and ignore any zero-count terms defensively. Reindex affected titles after the fix.

## Test

Feed an in-memory facet response with `OCR_TEXT` count zero and `OCR_ALTO` count positive; assert that only ALTO is reported as present.

## Related

- [GH2 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).
