# Run 01 — production baseline and first investigation target

## Scope and evidence

Read-only observations were made on 2026-10-20. Request windows are complete UTC days, 2026-10-18 and 2026-10-19. The source checkout is useful for possible call paths; its revision has not been matched to the deployed image. No production behavior was changed.

The ClickHouse `default.nginx_access_logs.endpoint` field is assigned using a **manually curated list of route patterns**. `endpoint = 'unknown'` means that a request did not match that list. It does not mean the request went to an unknown handler. This distinction matters here because the forwarded CDK IIIF routes are mostly in `unknown`. NGINX `response_time_ms` is an end-to-end proxy measure, not a Java method or Solr timing.

## Deployment and configuration

The observed deployment has two public and two curator pods using `docker.io/ceskaexpedice/kramerius:7.2.2.4`. The public image digest observed was `sha256:894e4fc69a21ba7e41531b91a3d62ef57c3040be75f70f9d761673f7b75d07ea`. A [later read-only check](11-deployment-incident-check.md) confirmed the curator pod uses the same digest and the gateway routes `/search/api/admin/` to curator, with other gateway traffic sent to public. There are eight default curator workers, one import worker, one public worker, and a process manager (`1.5`). The public pods mount Akubra object and datastream stores through separate 50 GiB NFS-class PVCs; these are provisioned sizes, not measured utilization.

The public ConfigMap and mounted `configuration.properties` have `api.monitor.threshold=1000` and a Solr logs collection URL. Neither showed a `cdk.server.mode` line. The deployed webapp's bundled configuration was checked for an explicit `cdk.server.mode` line and none was found. The checkout default is `false`, but the deployed image revision and complete configuration resolution are not established. A [later runtime check](13-iiif-runtime-paths.md) verified successful direct `info.json` requests on both public pods exercised the local non-CDK branch and showed the forwarded API as a separate executed entry point. This does not establish the full effective configuration or every request class.

## Public GET workload

Counts and 5xx values are exact for the named normalized endpoints. Latencies are milliseconds. October 19 quantiles use `quantilesExact`; October 18 quantiles use approximate `quantile`, so small day-to-day differences should not be overinterpreted.

| Route class | Oct 18 GET | p50 / p95 / p99 | 5xx | Oct 19 GET | p50 / p95 / p99 | 5xx |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct IIIF image tiles | 1,115,401 | 83 / 502 / 1245 | 1 | 1,287,720 | 118 / 632 / 1401 | 88 |
| Client image thumbs | 774,218 | 50 / 361 / 662 | 32 | 877,665 | 61 / 521 / 981 | 101 |
| Client search | 333,915 | 14 / 309 / 1188 | 1,159 | 377,902 | 22 / 421 / 1926 | 1,657 |
| Client item info | 61,539 | 93 / 544 / 1219 | 0 | 68,077 | 110 / 724 / 1517 | 0 |
| Direct IIIF `info.json` | 56,497 | 105 / 454 / 901 | 16 | 61,185 | 116 / 639 / 1172 | 23 |
| Client OCR text | 8,285 | 65 / 375 / 715 | 20 | 5,467 | 98 / 1215 / 4364 | 0 |

On October 19 there were 3,335,001 GETs and 1,972 GET 5xx responses in total. The curated `unknown` category held 290,464 GETs, about 8.7% of all GETs. A bounded aggregate using fixed path prefixes found 260,074 CDK API requests within that category. Of those, 241,801 were `/search/api/cdk/v7.0/forward/iiif/` GETs (p50 617 ms, approximate p95 2617 ms, one 5xx). Splitting the forwarded IIIF family by suffix gave 155,597 image-tile GETs (p50 625 ms, approximate p95 2637 ms, no 5xx) and 86,204 `info.json` GETs (p50 589 ms, approximate p95 2747 ms, one 5xx). These route-family figures use the actual path prefix/suffix, independent of the curated `endpoint` label. They are aggregate counts; no raw PIDs were retained.

The `OPTIONS` volume and latency must not be blended into image GET results. The earlier [IIIF pilot snapshot](pilot-iiif-info.md) counted 51,484 `OPTIONS` for the direct `info.json` route on October 19, with p50 3 ms.

## Reproduction and limits

The query path is a read-only client of the production ClickHouse. Use UTC half-open day windows (`timestamp >= '2026-10-19 00:00:00' AND timestamp < '2026-10-20 00:00:00'`), `request_method = 'GET'`, and `status >= 500` for the failure count. Group by curated `endpoint` for its defined classes; classify unmatched CDK IIIF paths separately with bounded `startsWith(path, '/search/api/cdk/v7.0/forward/iiif/')` and suffix predicates. Compute `count()`, `countIf(status >= 500)`, and `quantilesExact(0.5, 0.95, 0.99)(response_time_ms)` for selected classes. Use approximate `quantiles` when exact aggregation is too costly, and label the method. Set explicit `max_execution_time`, `max_memory_usage`, and `max_threads`; keep time windows and output narrow. A broad OTel attribute aggregation exceeded the ClickHouse memory limit and should not be repeated.

Example bounded query for a named endpoint (substitute one endpoint and one day at a time):

```sql
SELECT count() AS requests,
       countIf(status >= 500) AS errors_5xx,
       quantilesExact(0.5, 0.95, 0.99)(response_time_ms) AS latency_ms
FROM default.nginx_access_logs
WHERE timestamp >= '2026-10-19 00:00:00'
  AND timestamp < '2026-10-20 00:00:00'
  AND request_method = 'GET'
  AND endpoint = '/search/iiif/{pid}/info.json'
SETTINGS max_execution_time = 60, max_memory_usage = 1073741824, max_threads = 4;
```

For forwarded IIIF, replace the final `endpoint` predicate with `endpoint = 'unknown' AND startsWith(path, '/search/api/cdk/v7.0/forward/iiif/')`, then add `endsWith(path, '/info.json')` for metadata or the tile-path suffix used in the bounded route classification. Query settings are safety ceilings, not benchmark settings.

The NGINX access table has no trace ID, so individual request rows cannot currently be joined to OTel spans from that table. The `default.otel_traces` table had 6,731,910 `kramerius-public` spans on October 19, of which 14,369 were marked error; span errors do not equal failed requests. A five-minute trace sample found no spans named for `IiifServlet` or `reportAccess`. Dependency timings, CPU/GC, connection-pool waits, NFS latency, and worker utilization were not measured in this run. Thus the latency tables establish workload and symptoms, not root cause or component cost.

## Failures and investigation order

Client search had 1,657 GET 5xx responses on October 19: 1,655 HTTP 500 and two HTTP 502. The operator reports search failures are primarily associated with Solr downtime. A [subsequent downstream trace check](12-search-400-correlation.md) found Solr HTTP 400 responses in every failing search trace of two peak windows, and a deployed exception-class mismatch that maps these rejections to 500. The day-wide Solr-400 trace count is close to the search-500 count, but it is not a request-by-request join. The underlying Solr rejection reason and the two 502s still need investigation. Do not describe the sampled October 19 peaks as demonstrated Solr downtime, or use these failures as evidence that Elasticsearch would improve healthy search latency.

The first latency pilot should cover **both** direct and forwarded IIIF entry points. Direct tiles have the greatest counted volume, while forwarded IIIF has a markedly higher observed tail. The source checkout contains a forwarded API `info.json` route and access-log calls in `CDKIIIFResource`, so logging may also be relevant there. First confirm production routing and instrumentation, then compare critical-path time in authorization, Solr/Akubra reads, logging, upstream image service, and proxying. Only after that should an isolated logging or read-reduction experiment be selected. The focused [direct IIIF source graph](iiif-info-callgraph.svg) is a starting point, not runtime proof.

## Workload definitions and remaining inputs

- **Image opening:** direct and forwarded IIIF `info.json`, image tiles, client thumbnails, with cold/warm cache and concurrency classes; measure page-level image-ready time as well as route latency.
- **Searching:** representative query shapes, filters, result sizes, and healthy versus Solr-incident windows; measure latency, throughput, relevance, and failures separately.
- **Importing and indexing:** representative object/FOXML sizes and parent depth, job types, batch settings, documents/bytes per second, elapsed job time, visibility delay, and interactive-load interference. Current job baselines are missing.

To complete Run 01, obtain the deployed build revision and full effective CDK configuration, request-to-trace correlation where feasible, sanitized Solr-400 rejection reasons and incident timestamps, JVM/Solr/worker/NFS metrics, and representative import/indexing jobs. The public GET baseline and sampled executed IIIF paths are sufficient to choose an investigative pilot, but no causal performance improvement can yet be estimated.
