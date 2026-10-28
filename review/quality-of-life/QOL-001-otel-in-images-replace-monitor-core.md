---
id: QOL-001
former_id: IDEA-015
category: quality-of-life
title: Ship OpenTelemetry in the Kramerius images with tested defaults, and retire the hand-written API monitor and its Solr core
area: operations
impact: high             # makes performance and errors visible at every installation; removes a synchronous write from slow requests
effort: L                # agent and defaults in two image builds, monitor removal across ~22 files and an admin API, deploy examples
touches: [kramerius build (Jib images), shared/common monitoring, rest admin monitor API, process-platform worker image, kramerius-admin-client, kramerius-helm-chart]
contracts: [api, config, logs-semantics]
data_migration: false
use_cases: [image-open, search, indexing, ingest, admin]
review: [01-baseline, 13-iiif-runtime-paths]
---

# QOL-001 — Ship OpenTelemetry in the Kramerius images with tested defaults, and retire the hand-written API monitor and its Solr core

> **In one sentence:** almost every finding of this review came from OpenTelemetry traces that MZK had to bolt on through
> its Helm chart, while Kramerius carries its own partial monitor (timing code in ~22 classes, a `monitor` Solr core that
> keeps only calls over 1 s, written synchronously); shipping the agent in the images with tested defaults and a
> ClickStack deployment example would give every library the same visibility and let the hand-written monitor go.

## Today

**Kramerius's own monitor** (`origin/master` `560676c`):

- `APICallMonitor` / `ApiCallEvent` (`shared/common/.../cz/inovatika/monitoring/`): resources call
  `apiCallMonitor.start(...)` and `stop(...)` (7 classes) and record hand-made timing triples
  (`event.getGranularTimeSnapshots().add(Triple.of("solr/qtime", …))`) along the way; about 317 lines in 22 files.
- `SolrAPICallMonitor` (`rest/.../apiNew/monitoring/impl/SolrAPICallMonitor.java:106–126`, eager singleton,
  `BaseModule.java:60`): on `stop`, if the call took longer than `api.monitor.threshold` (1,000 ms by default), it builds an
  XML document and POSTs it to the `monitor` Solr core **on the request thread**. A slow request waits for one more Solr
  write.
- Only calls over the threshold are stored, so the core can say which calls were slow but not how slow calls are in
  general (no baseline, no percentiles).
- A separate Solr core per installation (`installation/solr-9.x*/monitor/`) and an admin endpoint
  `/admin/v7.0/monitor` (`APIMonitorResource`) that queries it.

**OpenTelemetry at MZK** (chart 1.3.2): the chart mounts the OTel Java agent from outside the image
(`templates/observability/_helpers.tpl:746–766`) into public, curator, process manager and workers (plugin JVMs through
`JAVA_TOOL_OPTIONS`), with method spans from an `includeMethods` list in the deploy values, a collector with tail sampling,
ClickHouse and HyperDX (ClickStack). With it the review found or measured PS-001, PS-002, KB-002, KB-005, PM-003, PM-004 and PM-001
(including the indexing numbers), none of which the `monitor` core could show.

**What MZK had to learn the hard way**, which defaults should encode:

- Tail sampling (errors, ≥ 1 s, 1% of the rest) needs weights when computing percentiles; numbers right after a restart are
  5–10× too high.
- All plugin JVMs report one service name (`worker-default`), so jobs cannot be told apart by service.
- Plugin code is not instrumented, so its Solr calls appear as root spans; Akubra's `ConcurrentUpdateSolrClient` shows as
  long POSTs that are not slow requests.
- Logs were not in ClickHouse: finding Solr's error reasons or a `ClassNotFoundException` meant reading Tomcat log files
  inside each pod.

## Idea

1. **The agent in the images, off by default.** Add the OpenTelemetry Java agent to the Kramerius images (Jib,
   `distZip jib` in `.github/workflows/gradle-dev.yml`) and the process-platform worker image, with `-javaagent` in the
   default JVM options and `OTEL_JAVAAGENT_ENABLED=false` unless the operator sets an endpoint. No chart tricks needed.
2. **Tested defaults in the image**, overridable by environment:
   - `service.name` per role (`kramerius-public`, `kramerius-curator`, `process-manager`, `worker`), and for plugin JVMs the
     process profile as a resource attribute (fixes the single `worker-default` name);
   - a default `includeMethods` set for the hot paths this review needed (rights resolution, Akubra reads and locks,
     access logging, indexer node build, process lifecycle);
   - the JUL log bridge on, so logs go to the same backend with trace IDs;
   - resource attributes for the installation (library code), so shared backends can tell libraries apart.
3. **Two documented levels**, so a library can start without a new database:
   - **Basic:** a collector with the `spanmetrics` connector only. It turns all spans into call counts and latency
     histograms per route, status and service, and exports them to Prometheus (or any metrics backend the library already
     has). Logs stay in files, now with trace IDs. No trace store; enough to see slow endpoints and error rates, which is
     more than the `monitor` core gives today.
   - **Full:** ClickStack (ClickHouse, OTel collector with the tail-sampling policy, HyperDX), for Docker Compose and for
     Helm, with the sampling caveats and ready queries (request percentiles weighted for sampling, slowest endpoints, error
     spans by type, job durations). This is what MZK runs.
4. **Retire the hand-written monitor.**
   - Replace `ApiCallEvent` timing triples with OTel spans: most are already covered by HTTP-client and JDBC spans; the
     few named stages that matter become `@WithSpan` methods or `includeMethods` entries.
   - Remove `SolrAPICallMonitor`'s synchronous write (an immediate win even before the rest).
   - Deprecate `/admin/v7.0/monitor` and the `monitor` core; point the admin client to the observability UI, or back the
     endpoint with a query to the OTel store for one release.
   - Keep the **statistics access log** (Solr `logs` core): that is library business data, not monitoring (see PM-003).

### How OpenTelemetry replaces each part of the monitor

The monitor stores, for each call over the threshold, one Solr document with `endpoint`, `resource`, `querypart`, `pid`,
`httpMethod`, `startTime`, `endTime`, `duration`, `statusCode`, `userId`, `ipaddress`, `granularSnapshot` (named
start/stop pairs) and `labels` (`ApiCallEvent.java:296–339`). Each piece has a standard OpenTelemetry counterpart:

| Monitor feature | OpenTelemetry replacement | Where it is configured |
| --- | --- | --- |
| `start` / `stop`, `endpoint`, `resource`, `httpMethod`, `statusCode`, `startTime`, `endTime`, `duration` | The HTTP server span the agent creates for every request: `http.route` (the resource template, e.g. `/client/v7.0/items/{pid}/ocr/text`), `url.path`, `http.request.method`, `http.response.status_code`, start and duration | Automatic (Tomcat/servlet and JAX-RS instrumentation) |
| `granularSnapshot` (`http/solr`, `solr/qtime`, `cache/…`, `http/<library>`) | Child spans: HTTP client spans for every Solr, image-server and CDK call (Apache HttpClient 4/5, Jersey client), JDBC spans for database work, and method spans for named stages | Automatic for clients and JDBC; named stages through `otel.instrumentation.methods.include` (or `@WithSpan` in code) |
| `pid` | Span attribute `kramerius.pid`, set once per request | A small Jersey `ContainerRequestFilter` (or servlet filter) that reads the `{pid}` path parameter and calls `Span.current().setAttribute(...)` |
| `labels` (from the `labels` configuration list) | Resource attributes, attached to every span and log | `OTEL_RESOURCE_ATTRIBUTES=kramerius.labels=…,kramerius.library=mzk` |
| `querypart` | Not recorded by default (it can contain search terms) | Opt in per parameter with the agent's `otel.instrumentation.servlet.experimental.capture-request-parameters`, or record only parameter **names** in the request filter |
| `userId`, `ipaddress` | Not recorded by default; `client.address` is available, the user only through an explicit opt-in (`enduser.id`) | The same request filter, behind a configuration flag; operators decide |
| The 1 s threshold (`api.monitor.threshold`) | Collector tail sampling: keep every trace ≥ 1 s (`latency` policy, `threshold_ms: 1000`) and every error, plus a small random share of the rest for percentiles | Collector config (the MZK chart already ships this policy) |
| Counts and percentiles over **all** calls (the monitor has none) | `spanmetrics` connector on an unsampled pipeline: call counts and latency histograms per route and status, computed before sampling | Collector config (optional pipeline in the MZK chart) |
| `monitor` Solr core (storage) | ClickHouse `otel_traces` / `otel_logs` with a TTL (e.g. 30 days) | Backend config |
| `commit()` | Not needed: the OTLP exporter batches in the background | — |
| `/admin/v7.0/monitor/search` | HyperDX saved searches and dashboards; for one release the endpoint can answer from ClickHouse instead of Solr | Backend, or a thin adapter in `APIMonitorResource` |

**Agent settings** (environment, all overridable; defaults baked into the image):

```properties
OTEL_JAVAAGENT_ENABLED=false                       # on only when the operator sets an endpoint
OTEL_SERVICE_NAME=kramerius-public                 # kramerius-curator, process-manager, worker per image/role
OTEL_RESOURCE_ATTRIBUTES=kramerius.library=<code>,deployment.environment=<env>
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_TRACES_SAMPLER=parentbased_always_on          # sample in the collector (tail), not in the JVM
OTEL_LOGS_EXPORTER=otlp                            # JUL log records with trace IDs, replacing log-file greps
OTEL_INSTRUMENTATION_COMMON_DB_STATEMENT_SANITIZER_ENABLED=true
OTEL_INSTRUMENTATION_METHODS_INCLUDE=cz.incad.kramerius.security.impl.http.RightsResolverFromRequest[isActionAllowed];org.ceskaexpedice.akubra.core.repository.impl.AkubraDOManager[readObjectFromStorage,doWithReadLock,doWithWriteLock];cz.incad.kramerius.statistics.accesslogs.solr.SolrStatisticsAccessLogImpl[reportAccess]
```

For plugin JVMs the worker adds the process profile and process ID as resource attributes
(`kramerius.process.profile`, `kramerius.process.id`), so jobs can be told apart.

**Collector policy** (as in the MZK chart, `templates/observability/_helpers.tpl:577–607`):

```yaml
tail_sampling:
  policies:
    - { name: errors,  type: status_code,       status_code: { status_codes: [ERROR] } }
    - { name: http-4xx-5xx, type: numeric_attribute, numeric_attribute: { key: http.response.status_code, min_value: 400, max_value: 599 } }
    - { name: slow,    type: latency,           latency: { threshold_ms: 1000 } }      # = api.monitor.threshold
    - { name: baseline, type: probabilistic,    probabilistic: { sampling_percentage: 1 } }
```

**The monitor's main question, answered from ClickHouse** ("which calls were slow, by endpoint"), with the sampling
weights documented in the cookbook:

```sql
SELECT SpanAttributes['http.route'] AS route, count() AS slow_calls,
       quantile(0.5)(Duration) / 1e6 AS p50_ms, max(Duration) / 1e6 AS max_ms
FROM otel_traces
WHERE ServiceName = 'kramerius-public' AND SpanKind = 'SPAN_KIND_SERVER'
  AND Duration >= 1e9 AND Timestamp >= now() - INTERVAL 1 DAY
GROUP BY route ORDER BY slow_calls DESC LIMIT 20
```

Calls of 1 s or more are kept in full, so this query is exact for them, as the monitor core was; percentiles over all calls
come from `spanmetrics` or from sampling-weighted queries.

## Expected gain

| Use case | Today | After (rough) | Confidence | Basis |
| --- | --- | --- | --- | --- |
| slow requests (> 1 s) | one extra synchronous Solr POST per slow request | none | high | source |
| every installation | only calls over 1 s recorded, no percentiles, no call tree | full traces, percentiles, call trees, logs with trace IDs | high | this review's use of OTel at MZK |
| operators | log files read inside pods | logs queryable next to traces | high | review practice |
| maintainers | ~317 lines of timing code in 22 files | removed or replaced by annotations | medium | source |

## Pros

- Every library gets the visibility MZK used to find most of its bugs, without building it themselves.
- Standard, vendor-neutral tooling: any OTLP backend works, ClickStack is only the documented example.
- Removes a Solr core, an admin endpoint, a synchronous write and scattered timing code.
- Shared defaults make numbers comparable between libraries (and feed QOL-003).

## Cons and risks

- Agent overhead: small, but measure CPU and latency with the default `includeMethods` before enabling by default anywhere.
- Image size grows by the agent jar (~20 MB).
- Libraries need a backend to benefit; without one the agent stays off. The basic level keeps that to a collector and a
  metrics store.
- Removing the `monitor` core and admin endpoint is an API change; some installations or the admin client may use it.
- Traces and logs can carry personal data (user names, IPs, query strings): the defaults must not record request
  parameters or user identifiers beyond what operators enable. (The `monitor` core stores user ID, IP address and query
  string of every slow call today, with no retention limit; the OTel defaults would be stricter.)

## Alternatives

1. **Do nothing.** MZK keeps its chart-level setup; other libraries have only the `monitor` core.
2. **Agent in the images only**, keep the monitor. Cheap, but keeps two systems and the synchronous write.
3. **Micrometer metrics** instead of traces. Gives rates and percentiles but no call trees, which is what found the bugs.
4. **Fix the monitor** (async write, sampling). Still a custom system with no call trees.
5. **Send OpenTelemetry data into Solr**, so libraries need no new database. Considered and rejected:
   - There is no Solr exporter in the OpenTelemetry Collector (core or contrib), and no Solr storage for Jaeger or Tempo.
     It would need a custom exporter (Go, built with the collector builder), an adapter service between the collector's
     OTLP/HTTP output and Solr's `/update`, or Kafka with a Solr sink. OTLP JSON cannot be loaded into Solr directly in a
     clean way: attributes are arrays of key/value objects, which Solr's JSON split mapping does not flatten well.
   - No trace UI reads Solr (HyperDX, Grafana Tempo, Jaeger), so trace views, call trees and dashboards would have to be
     written for Kramerius, which is the part the `monitor` core never had.
   - Traces are append-only, high-volume data queried by aggregation (percentiles, histograms); a columnar store does this
     cheaply, Solr does it slowly and with much memory. Expiry would need `DocExpirationUpdateProcessorFactory` or
     scheduled deletes.
   - It would keep a Kramerius-specific telemetry store that every library must run, which this idea removes. The basic
     level above meets the "no new database" goal better.

## Effort

**Size: L.** Several modules and two image builds change, and an admin API is removed.

| Part | Size | Why this size |
| --- | --- | --- |
| Remove the synchronous write in `SolrAPICallMonitor` (or make it async) | XS | One method; can ship first |
| Agent and default config in the Kramerius Jib images | S | Build config and a properties file |
| Same for the process-platform worker, with per-profile resource attributes | S | Worker image and plugin JVM options |
| Replace `ApiCallEvent` timing with spans; remove `APICallMonitor` | M | ~22 classes in `rest` and `shared/common` |
| Deprecate `/admin/v7.0/monitor`, the `monitor` core and the admin-client screen | M | API removal across two repos, one release of overlap |
| Basic level (collector with `spanmetrics` → Prometheus) and ClickStack examples (Compose, Helm), query cookbook | S | Docs and config; the MZK chart is the starting point |

## How we would validate it

1. Overhead: run the public app with the agent on and off under the same replayed load; accept if p50 changes < 5% and CPU
   < 10%.
2. Coverage: for one week at MZK, check that every question the `monitor` core answered (slowest endpoints, by resource)
   is answered by the OTel data, using sampling-weighted queries.
3. Adoption: one other library enables the image defaults with the example backend and reports whether setup took less
   than a day.

## Open questions

- Does anything outside the admin client read `/admin/v7.0/monitor` or the `monitor` core?
- Which `includeMethods` set is the right default: the MZK one is tuned for this review and may be too broad.
- Should the default sampling live in the SDK (head sampling, simpler) or in the collector (tail sampling, needs a
  collector)?
