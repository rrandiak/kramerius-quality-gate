# Phase 0 follow-up — deployed routing and search-error window

## Scope and method

Read-only checks on 2026-10-20–21 used the production cluster and bounded ClickHouse aggregates for 2026-10-19 UTC. No configuration values containing credentials, raw request URLs, user IDs, trace IDs, stack traces, or individual log rows were exported. Queries ran read-only against the production ClickHouse; all telemetry queries set `max_execution_time=30`, `max_memory_usage=1073741824`, and `max_threads=2`. The NGINX `endpoint` label is manually curated. This check used its exact client-search route class, not an assumption that every unmatched URL was unknown behavior.

## What is now verified

The public and curator pods both report image `docker.io/ceskaexpedice/kramerius:7.2.2.4` and the same image digest, `sha256:894e4fc69a21ba7e41531b91a3d62ef57c3040be75f70f9d761673f7b75d07ea`. They are separate deployments of the same build. The gateway OpenResty NGINX config sets `curator_path_prefix` to `/search/api/admin/`; its Lua `on_access` handler chooses the curator backend for that prefix and public otherwise. An independent `kramerius-curator` ingress also exists. This verifies a gateway route split, but does **not** prove that admin handlers are absent from public pods, that all alternate/direct paths are blocked, or that CPU/DB pools are isolated. Both roles share at least the same image and some backing services.

The gateway already runs a Lua rate limiter. Its access handler uses GCRA request accounting and download-byte accounting, a matched profile or client IP as identity, and Redis-backed counters. Username resolution is enabled, using the public user endpoint. Active rules, rejected counts, Redis failure behavior and added latency were not measured. This changes the rights-proxy question: a new rights-aware proxy would be for authorization or license entitlements, not to introduce the first rate limit ([Run 09](09-service-boundaries.md)).

The local `kramerius` checkout is `560676c85`, six commits past tag `v7.2.2.4`. The diff from that tag changes CDK reharvest/migration paths and adds a `CDKProcessResource` binding in `ApiServletModule`; the main IIIF, search, cache, collections, and folder files reviewed in Runs 02–09 are not listed in that six-commit diff. The deployed image tag makes the tag a plausible source anchor, but the image digest has not been tied to a Git commit, so revision equivalence remains unproven. Local `process-platform` is `v1.5.1-16-gda88e6a`; the observed manager image was `1.5`, also not commit-matched.

## Search error-window result

A day-wide five-minute aggregate of the curated client-search GET route found 5xx in many buckets, with spikes rather than one continuous failure period. The largest selected buckets by 5xx count included 23:55 (61), 13:55 (59), 04:40 (49), 14:25 (49), and 17:05 (44). The 13:45–14:05 window was inspected more narrowly:

| UTC bucket | Search GETs | HTTP 5xx | `SearchResource.get` error spans |
| --- | ---: | ---: | ---: |
| 13:45–13:50 | 1,358 | 4 | 4 |
| 13:50–13:55 | 1,214 | 2 | 2 |
| 13:55–14:00 | 1,706 | 59 | 61 |
| 14:00–14:05 | 1,573 | 8 | 8 |

The trace events in this window have `exception.type = cz.incad.kramerius.rest.apiNew.exceptions.InternalErrorException` for all 75 `SearchResource.get` error spans. A bounded aggregate over their `exception.message` and `exception.stacktrace` fields found no `Solr`, `connect`, or `timeout` keyword. A first `Caused by: ...Exception/Error` extraction returned no cause class. **Subsequent downstream-span analysis resolved the peak bucket:** all 59 distinct failing search traces contain a Solr HTTP 400 span ([correlation](12-search-400-correlation.md)). There are 61 Solr-400 spans because some traces contain more than one span. No trace-to-NGINX request ID is available from these tables.

The active public ConfigMap points `solrSearchHost` at the `k7-solr-cloud` namespace's `search_v22` collection. The intended Solr-400 catch uses an HttpClient 4 exception, while the Solr utility throws an HttpClient 5 exception, which is then mapped to `InternalErrorException` by the `IOException` catch. A later read-only deployed-bytecode check verified both class references in the running public pod. Current Solr pod metadata shows no pod restart on October 19. The sampled 400 responses prove Solr answered those requests, but their rejection reason is unknown. Solr server errors, schema/configuration and incident logs remain needed to distinguish a malformed application query from a collection problem.

The 13:55–14:00 bucket was route-specific: search accounted for 59 GET 5xx, and only one other curated endpoint class had a 5xx (one MODS metadata GET). Of 1,706 search GETs, 1,647 returned 200 and 59 returned 500. Search 200 latency was p50 26 ms / p95 353 ms; the 500s were p50 27 ms / p95 165 ms. The Solr-400 spans explain why the failures were quick; they are not timeout evidence. The original operator account remains useful context for other incidents, but this sampled spike is a Solr rejection plus application status-mapping issue, not a demonstrated Solr downtime.

## Reproducible safe aggregates

```sql
SELECT toStartOfFiveMinutes(timestamp) AS bucket_utc,
       count() AS search_gets,
       countIf(status >= 500) AS search_5xx
FROM default.nginx_access_logs
WHERE timestamp >= '2026-10-19 13:45:00'
  AND timestamp < '2026-10-19 14:05:00'
  AND request_method = 'GET'
  AND endpoint = '/search/api/client/v7.0/search'
GROUP BY bucket_utc ORDER BY bucket_utc
SETTINGS max_execution_time=30, max_memory_usage=1073741824, max_threads=2;
```

```sql
SELECT toStartOfFiveMinutes(Timestamp) AS bucket_utc,
       arrayFirst(x -> mapContains(x, 'exception.type'), Events.Attributes)['exception.type'] AS exception_type,
       count() AS error_spans
FROM default.otel_traces
WHERE Timestamp >= '2026-10-19 13:45:00'
  AND Timestamp < '2026-10-19 14:05:00'
  AND ServiceName = 'kramerius-public'
  AND SpanName = 'SearchResource.get'
  AND StatusCode = 'STATUS_CODE_ERROR'
GROUP BY bucket_utc, exception_type ORDER BY bucket_utc, error_spans DESC
SETTINGS max_execution_time=30, max_memory_usage=1073741824, max_threads=2;
```

## Next evidence gate

Obtain sanitized `k7-solr-cloud` HTTP-400 reason fingerprints, effective schema and incident metrics to identify why the requests were rejected. The linked [search check](12-search-400-correlation.md) defines a status-mapping regression test. Verify the gateway's alternate curator ingress and direct service access before claiming hard client/admin isolation. Match the image digest to a build commit for the broader audit; the specific search exception classes were verified in deployed bytecode. For the rights-proxy proposal, measure existing gateway rate-limit actions and user-resolution latency before designing a second limiter. No production state was changed.
