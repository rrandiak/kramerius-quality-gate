---
id: PS-002
former_id: BUG-003
category: perf-simple
title: Every rights check fetches the same Solr document again for each licence it evaluates
area: caching
severity: high
effort: S                # a per-check document cache in the criteria context; one module
use_cases: [image-open, search, admin]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read the rights check at Kramerius 560676c; warm OTel spans 2026-10-28, weighted"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-002 — Every rights check fetches the same Solr document again for each licence it evaluates

> **In one sentence:** a single `isActionAllowed` call queries Solr for the same document on average about 4 times, so
> three quarters of the Solr traffic in rights checks is repeats; warm, that is ~16 ms of a ~26 ms check, and rights checks
> are half of every direct IIIF request.

## Symptom

Rights checks are a large part of every protected request. On a warm system they take about half of a direct IIIF request
(26 ms of ~50 ms on average) and of an item or thumbnail API request, and they run on every image, tile and item request.
Right after a restart they are several times slower (`isActionAllowed` p50 ~200 ms, p95 ~730 ms on 2026-10-27).

## Cause

Kramerius `master` at `560676c`:

- `DatabaseRightsManager.resolve` (lines 238–262) loads the rights for the PID path, sorts them, and evaluates them one by one
  until one returns something other than `NOT_APPLICABLE`.
- Each licence criterion fetches the requested PID's Solr document itself:
  `Licenses.evalute` → `solrAccess.getSolrDataByPid(pid)` (`Licenses.java:55`). `LicensesIPFiltered`,
  `LicensesGEOIPFiltered` and `CriteriaLicenseUtils.checkDnnt` (line 37) follow the same pattern.
- With several licences configured, every licence that does not apply costs another identical Solr round trip.
- The caller has usually loaded the same document already: `getPidPaths` reads it before the rights check starts.

## Evidence and frequency

OTel spans on `kramerius-public`. Counts are from hashed URLs; no URLs were exported. The warm measurement is weighted for
the collector's tail sampling (every trace with an error or of 1 s or more is kept, 1% of the rest; weight 1 or 100).

| Metric | Warm, 2026-10-28, 1 h, weighted | First measurement, 2026-10-27, 30 min after a restart, unweighted |
| --- | ---: | ---: |
| `isActionAllowed` calls with Solr GETs | ~50,500 (5,415 kept) | 4,914 |
| Solr GETs per call, average | **3.91** | 5.64 |
| **Distinct URLs per call, average** | **1.00** | **1.00** |
| Repeated share of those GETs | **74%** | 82% |
| Time in repeated GETs per call | **15.9 ms** average, 9.7 ms p50 | 104 ms average |
| Most GETs in one call | 9 | 36 |
| Solr GET (`/solr/search_v22/select`) p50 / p95 | 4.4 / 9.5 ms | 6.9 / 84 ms |

Rights cost per request by route (requests with at least one rights check):

| Route | Requests (warm, 1 h) | Rights calls per request | Rights time per request, warm (avg / p50) | Share of request time, warm | Rights time per request, first measurement |
| --- | ---: | ---: | ---: | ---: | ---: |
| direct IIIF (`/search/iiif/*`) | ~29,900 | 1.0 | 26 / 19 ms | **52%** | 276 ms |
| CDK forward | ~7,800 | 1.1 | 46 / 37 ms | 19% | 314 ms |
| other API (`/search/api/*`, items and thumbs) | ~11,500 | 5.4 | 40 / 25 ms | **49%** | 567 ms |

## Impact

- **Latency:** removing the repeats saves ~16 ms of a ~26 ms check when warm, about **a third of a direct IIIF request**,
  and proportionally more on item routes, which make ~5 checks per request. Right after a restart the saving was ~100 ms
  per check.
- **Solr load:** about three quarters fewer queries from rights evaluation, roughly 150k fewer Solr queries an hour on the
  main Solr core (~50k checks an hour × ~2.9 repeats). Image routes alone serve over 1.3M requests a day.
- **Tail:** each repeat can hit Solr's tail, so a slow Solr is multiplied by the number of licences evaluated.

## Fix

Fetch the document once per check:

1. Add a lazily loaded, memoized "requested PID Solr document" to `RightCriteriumContext`, filled on first use.
2. Make `Licenses`, `LicensesIPFiltered`, `LicensesGEOIPFiltered` and `CriteriaLicenseUtils.checkDnnt` read it from the context.
3. Optional: let callers that already hold the document (after `getPidPaths`) seed the context, which removes the last fetch too.

The cache lives only for one check (one context), so no invalidation is needed and rights semantics do not change.

## Test

- Unit test: a path with several non-matching licences followed by a matching one triggers exactly one `getSolrDataByPid` call.
- Staging or production after the fix: the Solr GETs per `isActionAllowed` call (`avg_gets` in the query above) drop from ~3.9
  to ≤ 1, and the `isActionAllowed` time drops by ~16 ms on average when warm.

## Related

- [PS-001](PS-001-forward-resource-graph-per-request.md) and [PM-003](../perf-medium/PM-003-batched-access-log-writer.md):
  the other large costs on IIIF and forwarded requests.
- Still unexplained (first, cold measurement): about 80–100 ms of `isActionAllowed`'s own time was not covered by child spans. Candidates are the unused
  connection taken by `InitSecurityDatabaseMethodInterceptor` on every `resolve` and waiting for the 20-connection Hikari pool.
- The existing `RightsResolverFromRequestCached` caches whole decisions, but only on the Zoomify tile route
  ([review 20](../raw/20-rights-boundary.md)). Caching decisions is a separate, larger idea with real freshness questions.
  This fix only removes redundant reads and has none.
