---
id: BUG-023
former_id: BUG-024
category: bug
title: The Solr search configs set the default field to "text", which no Kramerius schema defines, so any unfielded query word fails
area: search
severity: medium
effort: S                # one line in three solrconfig.xml files; existing installs must re-upload their search config
use_cases: [search]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read the shipped Solr configs at Kramerius 560676c; 7 days of MZK Solr error templates and NGINX query shapes"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-023 — The Solr search configs set the default field to "text", which no Kramerius schema defines, so any unfielded query word fails

> **In one sentence:** every Kramerius 7 search core is configured with `df=text`, a field that does not exist in its
> schema, so any query word without a field prefix makes Solr reject the whole query; at MZK an older web client's search
> inside a document hits this about 1,000 times a day.

## Symptom

Searching for several words inside a document from an older web client fails with a server error (500, see
[BUG-017](BUG-017-search-solr-400-returned-as-500.md)); one word works. Solr's log reason is
`undefined field text`.

## Cause

Kramerius `origin/master` at `560676c`:

- The Solr 9 search configs set the default field for `/select` to `text` in their `initParams`:
  `installation/solr-9.x/search/solrconfig.xml:821`, `installation/solr-9.x.cloud/search/solrconfig.xml:835`, and
  `installation/solr-9.x.cdk/search/solrconfig.xml:650` and `:656`. The value matches Solr's old sample config.
- None of the search schemas (`managed-schema.orig`, `managed-schema.input`) defines a field `text`.
- With the standard query parser, a word without a field prefix is searched in `df`. In `text_ocr:word1 word2`, only `word1`
  is bound to `text_ocr`; `word2` goes to `text`, and Solr rejects the query with 400.

**The trigger is a client.** An older web client builds the in-document search as `q=text_ocr:<user's words>` with
`fq=own_parent.pid:…` and highlighting, without grouping the words (`text_ocr:(…)`). Whatever the client does, the default
field can never work: no Kramerius 7 search schema has `text`.

## Evidence and frequency

MZK production, 7 days to 2026-10-28, read-only:

- **Solr's reasons** in the public pods' logs: `undefined field text` 9,874 records, 69% of all Solr errors (masked
  templates; no query text exported).
- **NGINX, in-document searches** (`q=text_ocr:…`, `fq=own_parent.pid:…`, highlighting), by the shape of `q` (yes/no
  features only, no values exported):

| `q` shape | Failed (500) | OK (200) | Failure rate |
| --- | ---: | ---: | ---: |
| `text_ocr:` + several words, not grouped | 7,033 | 5,962 | **54%** |
| `text_ocr:"…"` (quoted) | 353 | 3,121 | 10% |
| `text_ocr:` + one word | 14 | 32,483 | 0.0% |
| `text_ocr:(…)` (grouped) | 13 | 60 | 18% |
| other | 64 | 34,856 | 0.2% |

  The ungrouped shape probably also contains queries that repeat the field for each word (`text_ocr:a AND text_ocr:b`),
  which succeed; that would explain why it fails about half the time, not always. The quoted failures overlap with syntax
  errors (unterminated quotes with `*`).
- Almost all failing requests come from browsers on `www.digitalniknihovna.cz`, at a steady 1,000–1,700 a day.

## Impact

- Users of the affected client get an error instead of results for multi-word searches inside a document.
- Any other client or script that sends an unfielded word gets the same error; the API gives no hint (500, BUG-017).
- The Kramerius 7 and CDK search configs all ship with this `df`, so installations that use them reject the same queries.

## Fix

1. **Kramerius (report upstream):** point `df` at a field that exists in all three search configs, for example `text_ocr`
   (what an unfielded word in a full-text search most likely means), or remove the `df` entry and document that every word
   needs a field. No query that works today changes behaviour, because every query that uses `df` fails now. Existing
   installations must update the config of their search collection (SolrCloud: upload the configset and reload).
2. **Client:** the older web client should group the user's words, `text_ocr:(word1 word2)`, or escape them as a phrase.
3. With [BUG-017](BUG-017-search-solr-400-returned-as-500.md) fixed, such queries return 400 with Solr's reason instead of 500.

## Test

- Against a search core with the shipped config: `q=text_ocr:alpha beta` must not return `undefined field text`; with
  `df=text_ocr`, it matches documents whose OCR contains `beta`.
- Production after the config change: `undefined field text` disappears from the logs, and the failure rate of ungrouped
  in-document searches drops to the level of single-word ones.

## Related

- [BUG-017](BUG-017-search-solr-400-returned-as-500.md): the same failures reach clients as 500.
- [PM-005](../perf-medium/PM-005-elasticsearch-vs-solr.md): an engine-neutral search API would build field queries itself
  instead of passing user syntax to Solr.
