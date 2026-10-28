# IIIF `info.json` — executed paths in sampled production traces

## What the traces establish

Read-only aggregates over **2026-10-19 11:30–11:35 UTC** selected successful server spans by route and `/info.json` suffix, then counted spans sharing their trace IDs. No PID, URL with query, user, trace ID, or individual span was exported. The NGINX `endpoint` label is manually curated; the forwarded route was selected using its actual path prefix. This is an executed-path check, **not** a representative latency or call-count benchmark.

| Successful route in trace sample | Distinct traces | Solr search GET | Solr logs POST | Akubra object-read spans | Image-server GET |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct `/search/iiif/.../info.json` | 8 | 69 in 8 traces | 9 in 8 traces | 37 in 8 traces | 9 in 8 traces |
| Forwarded `/search/api/cdk/v7.0/forward/iiif/.../info.json` | 70 | 417 in 70 traces | 71 in 70 traces | 284 in 70 traces | 71 in 70 traces |

The Solr paths were `/solr/search_v22/select` for GET and `/solr/logs/update` for POST; image calls went to `imageserver-proxy.k7-imageserver.svc.cluster.local`. Each selected trace contains a logs POST and an image-server GET. The logs POST started before the image-server GET in **8/8 direct** and **70/70 forwarded** traces. This confirms that a request-time Solr logs write is exercised on both successful entry points in this sample. `CoreRepositoryImpl.getAsBytes`, `AkubraDOManager.retrieveObjectBytes`, and `AkubraLowlevelStorage.retrieveObject` each appeared 37 times in the direct sample and 284 times in the forwarded sample; these are nested spans representing the same object reads, not three independent read counts.

The direct route's local Solr reads, Akubra reads, logs write, and image-server call match the checked source's **non-CDK direct branch** (`IiifServlet.java:92–229`). Successful direct traces came from both `kramerius-public-0` (six distinct traces) and `kramerius-public-1` (two). The forwarded API's observed calls match `CDKIIIFResource`'s logging path. This verifies those executed paths in the sampled deployment; it does not prove every request or configuration branch, and the image digest still lacks a source-commit match.

## Sampling and interpretation limits

The direct trace sample had nine successful server spans across eight trace IDs; NGINX counted **293** successful and **20** forbidden direct `info.json` GETs in that window. The forwarded route had 70 sampled successful trace IDs versus **204** successful and **three** forbidden NGINX GETs. Across the full day, the same curated direct route had 53,238 HTTP 200, 7,849 HTTP 403, 75 HTTP 499, and 23 HTTP 500. Neither trace set should be treated as an unbiased draw from all successful requests. Another five-minute trace slice (13:55–14:00) contained 36 direct `info.json` 403 spans and only one 200; its high Solr fan-out describes denied-access behavior and should not be used as the image-opening baseline.

The Solr GET counts include rights, path lookup and access-log enrichment, but there is no dedicated `reportAccess` span to divide them. The logs POST span measures only its HTTP call, not the whole enrichment path. Some traces have more than one server or client span, and parent/child durations overlap. These aggregates establish that logging participates before the image-server call; they **do not** establish its critical-path share or a speed gain from moving it.

## Reproducible bounded method

Select distinct `TraceId` from `default.otel_traces` in a five-minute UTC window with `ServiceName = 'kramerius-public'`, `SpanKind = 'SPAN_KIND_SERVER'`, `SpanAttributes['http.response.status_code'] = '200'`, and `endsWith(SpanAttributes['url.path'], '/info.json')`. For direct requests use `SpanName = 'GET /search/iiif/*'`; for forwarded use `SpanName = 'GET /search/api/cdk/v7.0/forward/*'` plus `startsWith(SpanAttributes['url.path'], '/search/api/cdk/v7.0/forward/iiif/')`. Restrict child scans to the same time window, service, selected trace IDs, and `SPAN_KIND_CLIENT` or the three Akubra `SPAN_KIND_INTERNAL` names. Group by `SpanName`, `server.address`, and `extract(url.full, '^https?://[^/]+([^?]*)')`; never return the full URL. For ordering, group child spans by trace ID internally and return only `countIf(minIf(Timestamp, logs_POST) < minIf(Timestamp, image_GET))`. All queries used `max_execution_time=30`, `max_memory_usage=1073741824`, `max_threads=2`.

## Next measurement gate

Add a dedicated bounded span around access-log enrichment and write, separating its Solr reads, Akubra/FOXML reads and Solr POST from rights, repository metadata and image-server time. Record branch and outcome classes, warm/cold state, and representative request shapes without identifiers. Compare direct and forwarded routes under controlled staging load and measure browser image-ready time and logging durability. Until that exists, keep the IIIF logging change as a pilot candidate rather than a claimed optimization. No production state was changed.
