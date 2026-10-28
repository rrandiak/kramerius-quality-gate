---
id: PS-001
former_id: BUG-002
category: perf-simple
title: Every CDK forward request builds two new HTTP clients and the whole forward resource graph before any forward code runs
area: modularization
severity: high
effort: S                # resource wiring in one module; no API, schema or data change
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read the CDK forward resources at Kramerius 560676c; warm OTel spans 2026-10-28, weighted, checked against NGINX"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-001 — Every CDK forward request builds two new HTTP clients and the whole forward resource graph before any forward code runs

> **In one sentence:** Guice and Jersey build the large, unscoped `CDKForwardResource` object graph for every request on
> `/search/api/cdk/v7.0/forward/*`, including two new Jersey HTTP clients that are never closed; on a warm system this
> costs a median of ~120 ms before the resource method starts, and the two `Client.create()` calls alone are about **half of
> all forward request time**.

## Symptom

Forwarded IIIF requests spend a large part of their time before the forward code starts (warm system, 2026-10-28,
weighted for trace sampling, see below):

| Route | Request p50 / p95 | Gap before the method, p50 / p95 |
| --- | ---: | ---: |
| forwarded `info.json` | 214 / 400 ms | **124 / 278 ms** |
| forwarded tile | 159 / 363 ms | **121 / 303 ms** |

Right after a restart the gap is several times larger (0.8–1.3 s at the median on 2026-10-27, cold JIT and caches).

## Cause

Kramerius `master` at `560676c`:

- `ApiServletModule.java:136–137` binds `CDKForwardResource` and `CDKIIIFResource` **without a scope**, and so are the other
  resources `CDKForwardResource` injects. Jersey with Guice therefore builds the graph per request.
- `CDKForwardResource` injects 9 sub-resources directly (`CDKUsersResource`, `CDKItemResource`, `CDKIIIFResource`,
  `CDKZoomifyResource`, `SOLRResource`, `PDFResource`, `ItemsResource`, `UsersRequestsResource`, …), about 70 injection points
  in total. A tile request uses one of them but builds all of them.
- `CDKIIIFResource` and `CDKZoomifyResource` extend `AbstractTileResource`, whose constructor calls `Client.create()`
  (`AbstractTileResource.java:37`). That builds two Jersey 1 clients, which are never closed. `CDKIIIFResource` doesn't use this
  client for IIIF; it uses `RESTHelper` and the injected async client.

The exact split of the remaining construction cost inside Guice and Jersey is not measured, because the OTel agent does not trace those libraries.

## Evidence and frequency

**Warm system, 2026-10-28** (3-hour window, OTel spans on `kramerius-public`). The collector keeps every trace with an
error or of 1 s or more and 1% of the rest, so each kept trace is weighted 1 or 100. The weighted request estimate is within
±15% of the NGINX request counts for the same routes and window.

| Measure | Result |
| --- | --- |
| Gap from the innermost filter to the resource method, `iiiFManifest` (n 4,683) | p50 124 ms, p95 278 ms |
| Same, `tile` (n 175) | p50 121 ms, p95 303 ms |
| Forward requests that call `Client.create()` | **100%** (of ~25k estimated), always twice |
| `Client.create()` per call | p50 45 ms, p95 115 ms |
| `Client.create()` share of all forward request time | **52%** |

**First measurement, 2026-10-27** (about 30-minute windows right after instrumented restarts, so cold; unweighted):

- **Gap between the innermost `ExtAuthFilter.doFilter` and the resource method**, measured the same way for each route:

  | Resource method | n | Gap p50 | Gap p95 |
  | --- | ---: | ---: | ---: |
  | `CDKForwardResource.tile` | 367 | 1,264 ms | 3,196 ms |
  | `CDKForwardResource.iiiFManifest` | 548 | 835 ms | 2,501 ms |
  | `ItemsResource.getImgThumb` | 242 | 18 ms | 602 ms |
  | `ItemsResource.getInfo` | 124 | 10 ms | 102 ms |
  | `SearchResource.get` | 231 | 0.4 ms | 4.4 ms |

  The same filters and dispatch cost under a millisecond for search, so the gap is specific to the forward resource.
- **`Client.create()`:** p50 753 ms, p95 1.6 s per call (cold). It was seen on 21–37% of forward requests, always twice per
  request, and accounted for 15–19% of forward request time. Only the forward route calls it (510 of 511 calls).
- **Things ruled out:** response writing after the method (~0 ms); the CDK API-key check (~4 ms); the CDK user setup
  (runs on 18% of requests, ~50 ms average); the Guice providers for the forward, async and Solr clients (all singletons).

Volume: about 240k forwarded IIIF requests a day (2026-10-19 baseline: 86k `info.json` and 156k tiles).

## Impact

- **Latency:** about half of every forwarded image request is spent here when warm (~90 ms of two `Client.create()` calls
  at the median), and most of the request right after a restart. At ~240k forwarded requests a day that is about 6 hours of
  request time a day.
- **Resources:** two new HTTP clients on every forward request, never closed: about half a million a day, which adds
  allocation and GC pressure and may contribute to the long tail.

## Fix

Smallest change that removes the cost, all inside the `rest` module:

1. In `CDKForwardResource`, inject the sub-resources as `Provider<…>` and call `.get()` only in the method that needs them.
   A tile request then builds only `CDKIIIFResource`.
2. Remove `Client.create()` from the `AbstractTileResource` constructor. Inject the existing `@Named("forward-client")` singleton,
   or create the client lazily on first use if anything needs it.
3. Optionally bind `CDKIIIFResource` and `CDKZoomifyResource` as singletons. Their fields are injected services and providers,
   but check them for thread safety first.

## Test

- Before and after on staging with forwarded tile and `info.json` load: the auth-filter-to-method gap should fall to the
  level of `SearchResource.get` (a few ms), and `Client.create` spans should disappear from forward traces.
- A functional check that every forward endpoint still works, since each one now resolves its sub-resource lazily.

## Related

- [PM-003](../perf-medium/PM-003-batched-access-log-writer.md): access logging is about 15% of forwarded `info.json` time
  (p50 ~30 ms, warm).
- Remaining forward costs after this fix, from the cold 2026-10-27 measurement: the rights check `permitted()` (~300–390 ms,
  with `isActionAllowed` p50 200 ms per call) and the CDK user setup (~50 ms average). Re-measure warm before writing them up.
- The same unscoped pattern probably affects `ItemsResource` routes on a smaller scale (thumb gap p95 602 ms).
