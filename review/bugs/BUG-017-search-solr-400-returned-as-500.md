---
id: BUG-017
former_id: BUG-023
category: bug
title: The search API answers 500 when Solr rejects a query, because it catches the wrong HttpResponseException class
area: search
severity: medium
effort: XS               # one import (or catch both classes) in SearchResource; one test
use_cases: [search]
review_ref: [B11]
upstream: null
checked: [source, production]
checked_how: "Read the search resource at Kramerius 560676c; 7 days of MZK NGINX logs and public-pod Solr error templates"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-017 — The search API answers 500 when Solr rejects a query, because it catches the wrong HttpResponseException class

> **In one sentence:** `SearchResource` catches the Apache HttpClient 4 `HttpResponseException`, but the Solr call throws
> the HttpClient 5 class of the same name, so every query Solr rejects with 400 (bad syntax, unknown field) reaches the
> client as a 500 server error, about 1,000 a day at MZK.

## Symptom

`GET /search/api/client/v7.0/search` returns **500 Internal Server Error** for queries that are the client's fault: a field
that does not exist, unbalanced quotes, a sort on an unsortable field. Clients cannot tell a bad query from a server failure,
monitoring counts them as server errors, and the "Bad Request" log line with the API and Solr request that was meant for this
case never appears.

## Cause

Kramerius `origin/master` at `560676c`:

- `SolrUtils.requestWithSelectReturningStream` throws `org.apache.hc.client5.http.HttpResponseException` for any non-200
  Solr answer (`shared/common/.../utils/solr/SolrUtils.java:45`, `:619–623`). In HttpClient 5 this class is an `IOException`.
- `SearchResource` imports `org.apache.http.client.HttpResponseException` (HttpClient 4, `SearchResource.java:39`) and
  catches that in `buildSearchResponseJson` and `buildSearchResponseXml` (`:175`, `:208`). The class never matches.
- The exception falls through to `catch (IOException e)` (`:188`, `:219`) and becomes `InternalErrorException` (500). The
  400 branch (`:176–184`, `:209–214`) is dead code.
- Before throwing, `SolrUtils` logs Solr's error body as `Error message …` (`:621`), so the reason is in the Tomcat log.

The deployed classes reference the same types (verified with `javap` during the review, see
[run 12](../raw/12-search-400-correlation.md)).

## Evidence and frequency

MZK production, 7 days to 2026-10-28, read-only:

- **NGINX, public search endpoint:** 8,938 answers with 500, 647 with 400 (the 400s come from Kramerius's own parameter
  checks, which throw `BadRequestException` directly), of about 2.7 M search requests.
- **Solr's reasons**, from the `Error message` log lines in both public pods (14,342 records; masked templates, no query
  text exported). The log covers every `SolrUtils` select caller, not only `/search`, so it has more records than NGINX 500s:

| Solr's reason | Records | Should the client get |
| --- | ---: | --- |
| `undefined field text` (see [BUG-023](BUG-023-search-default-field-does-not-exist.md)) | 9,874 | 400 |
| query syntax errors (`Cannot parse …`) | ~600 | 400 |
| old field names (`title`, `dc.title`, `fulltext`, `_text_`), unsortable sort fields, invalid dates | ~200 | 400 |
| `no active servers hosting shard`, Solr connection, DNS and idle timeouts | ~3,400 | 5xx (correct) |

So about three quarters of these errors (≈ 1,000 a day) are client errors that should have been 400.

## Impact

- Clients and the web client show a server error for a bad query and cannot tell the user what to fix.
- Error-rate monitoring and alerting on 5xx counts mostly client mistakes, which hides real Solr outages (the ~3,400
  availability errors) in the noise.
- The logs miss the intended "Bad Request (api request = …, solr request …)" line, which would make these cases easy to trace.

## Fix

In `SearchResource`, catch `org.apache.hc.client5.http.HttpResponseException` instead (change the import), keep the 400
branch, and map other Solr status codes to 502 or 503 rather than 500. The same HttpClient 4 import is in three more classes that may
catch exceptions from HttpClient 5 code: the K5 `SearchResource` (`rest/.../api/k5/client/search/`), `ZoomifyHelper` and
`SolrStatisticsAccessLogImpl`; check each catch.

## Test

- API test with a stubbed Solr that answers 400 with a JSON error body: `GET /search` returns 400 and the body names the
  problem; with 503, the API returns 5xx.
- Production after the fix: on the search endpoint, the 500 count falls by about three quarters and the 400 count rises by
  the same amount.

## Related

- [BUG-023](BUG-023-search-default-field-does-not-exist.md): the cause of most of these 400s.
- [PM-005](../perf-medium/PM-005-elasticsearch-vs-solr.md): an engine-neutral search API would validate queries before they
  reach Solr.
