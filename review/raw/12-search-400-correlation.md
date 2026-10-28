# Search 500s and Solr 400s — bounded causal check

## Result and limits

Read-only ClickHouse aggregates for **2026-10-19 UTC** identify an active application error-mapping issue. In the 13:55–14:00 and 23:55–00:00 five-minute spikes, every distinct error trace for `SearchResource.get` also contains a failed HTTP client span to Solr with response **400**: 59/59 and 61/61 traces, respectively. The corresponding manually curated NGINX client-search route has 59 and 61 HTTP 5xx responses. Trace IDs are not present in the NGINX table, so these counts do not establish a request-by-request join to NGINX.

For the full day, `kramerius-public` has **1,671** failed HTTP client spans to `/solr/search_v22/select` with status 400, across **1,653 distinct traces**. The curated client-search route has **1,655 HTTP 500** and **two HTTP 502** responses. The close counts, same collection path, and two trace-linked windows strongly indicate this is a dominant failure pattern, but a full-day trace-ID intersection was not completed: that query hit ClickHouse's total memory limit despite a 1 GiB per-query setting. Do not equate 1,653 traces with 1,653 particular NGINX requests or claim all 1,657 route failures have the same cause.

Other high-5xx buckets reinforce the pattern without a trace-ID join: 04:40 had 49 Solr-400 traces versus 49 search 5xx; 14:25 had 49 versus 49; 17:05 had 44 distinct Solr-400 traces (51 spans) versus 44 search 5xx. Other failed image-server client spans occur in some windows and are unrelated to this Solr count. An HTTP 400 proves Solr answered these requests; it does **not** support a claim that these particular failures were connection failures or a total Solr outage. The operator's report that search failures usually accompany Solr downtime may describe other dates/incidents, a different failure mode, or a schema/collection incident that causes Solr to reject queries. Solr's 400 response body, effective schema and server logs are needed to distinguish malformed client queries from an index/configuration problem. No raw query URL or response body was exported.

## Source mechanism

`SearchResource.java` imports `org.apache.http.client.HttpResponseException` (Apache HttpClient 4) and has a special `catch (HttpResponseException)` path intended to turn Solr 400 into a client `BadRequestException`. Its `@Named("new-index")` `SolrAccessImplNewIndex` delegates to `SolrUtils.requestWithSelectReturningString`. `SolrUtils.java` imports and throws **`org.apache.hc.client5.http.HttpResponseException`** (Apache HttpClient 5) for non-200 Solr responses. These are different classes. The HttpClient 5 exception therefore bypasses the special catch and falls into `catch (IOException)`, which throws `InternalErrorException`; the observed trace exception class matches this path. **Read-only javap inspection in the running kramerius-public-0 pod confirmed both exception references in the deployed classes.** The mismatch is active in the deployed build and explains the observed status mapping; the exact image-to-source commit remains unknown. The underlying reason Solr returned 400 remains unknown.

`ZoomifyHelper.java` also imports the HttpClient 4 exception, but its shown HTTP client is HttpClient 4, so that import is not evidence of the same defect. `StatisticsResource.java` and `SolrAPICallMonitor.java` use the HttpClient 5 import. Search's broad outer `catch (Throwable)` is an additional error-mapping risk but not needed to explain the observed mechanism.

## Reproducible safe aggregates

The following queries output only counts, dependency names, statuses, or internal path names. Keep the five-minute bounds for the trace-ID intersection; the full-day version exceeded the server's total memory limit.

```sql
SELECT SpanAttributes['server.address'] AS dependency,
       SpanAttributes['http.response.status_code'] AS downstream_status,
       count() AS spans,
       uniqExact(TraceId) AS traces
FROM default.otel_traces
WHERE Timestamp >= '2026-10-19 13:55:00'
  AND Timestamp < '2026-10-19 14:00:00'
  AND ServiceName = 'kramerius-public'
  AND SpanName = 'GET'
  AND SpanKind = 'SPAN_KIND_CLIENT'
  AND StatusCode = 'STATUS_CODE_ERROR'
GROUP BY dependency, downstream_status
ORDER BY spans DESC
SETTINGS max_execution_time=30, max_memory_usage=1073741824, max_threads=2;
```

```sql
WITH solr_400 AS
    (SELECT DISTINCT TraceId FROM default.otel_traces
     WHERE Timestamp >= '2026-10-19 13:55:00'
       AND Timestamp < '2026-10-19 14:00:00'
       AND ServiceName = 'kramerius-public'
       AND SpanName = 'GET' AND SpanKind = 'SPAN_KIND_CLIENT'
       AND SpanAttributes['server.address'] = 'solr.k7-solr-cloud.svc.cluster.local'
       AND SpanAttributes['http.response.status_code'] = '400'),
search_errors AS
    (SELECT DISTINCT TraceId FROM default.otel_traces
     WHERE Timestamp >= '2026-10-19 13:55:00'
       AND Timestamp < '2026-10-19 14:00:00'
       AND ServiceName = 'kramerius-public'
       AND SpanName = 'SearchResource.get'
       AND StatusCode = 'STATUS_CODE_ERROR')
SELECT (SELECT count() FROM solr_400) AS solr_400_traces,
       (SELECT count() FROM search_errors) AS search_error_traces,
       (SELECT count() FROM search_errors
        WHERE TraceId IN (SELECT TraceId FROM solr_400)) AS shared_traces
SETTINGS max_execution_time=30, max_memory_usage=1073741824, max_threads=2;
```

The peak-window result is `59 / 59 / 59`; the same query with 23:55–00:00 bounds yields `61 / 61 / 61`. The day-wide count came from a single aggregate over failed client `GET` spans, grouped by `server.address`, response status and sanitized URL path. An attempted full-day join failed with `MEMORY_LIMIT_EXCEEDED`; it produced no usable count and was not retried.

## Action and validation gate

1. In an isolated test, make Solr return 400 and verify whether the public API responds 400 or 500. Correct the exception import/handling and add a regression test for both 400 and 5xx/connection failures. Preserve a safe, structured error category without logging raw user queries. An exact image-to-source-commit match is still needed for broader audit conclusions.
2. Use authorized, sanitized Solr response-body or server-log fingerprints plus the effective schema to determine **why** 400 occurred. Compare several failed query shapes with successful ones, without exposing query terms, PIDs or credentials. Fix invalid query construction or schema/configuration separately from HTTP status mapping.
3. Reclassify search incidents by upstream status, timeout/connect error and application exception before deciding on Solr topology, retries, a rate limit, or an engine change. Measure reduction of misclassified 500s and the true user-visible search success rate. A corrected 400 alone improves diagnosis, not successful search throughput.

No production state was changed.
