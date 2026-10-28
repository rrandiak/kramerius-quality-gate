---
id: KB-003
former_id: BUG-004
category: known-bug
title: Every image opened through the CDK is counted as dozens of views in the source library's statistics
area: cdk
severity: high
effort: S                # CDK servlet: per-image probe cache and a probe marker; source: skip logging for probes
use_cases: [image-open]
review_ref: []
upstream: "ceskaexpedice/kramerius#1362"
checked: [source, production]
checked_how: "Read the CDK forward and IIIF code at Kramerius c2a05c0 and 560676c; controlled single-open test and MZK forwarded info.json counts 2026-10-27; kramerius#1362"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-003 — Every image opened through the CDK is counted as dozens of views in the source library's statistics

> **In one sentence:** when a reader opens an image on ceskadigitalniknihovna.cz, the CDK fetches the source library's full `info.json` before nearly every tile, and every one of those fetches is recorded as a view, so **one image open becomes 17–34 views in the source's statistics**, plus as many rights checks and `info.json` runs, while the reader waits up to seconds per tile.

## Symptom

One map page (model `map/page`) opened once on ceskadigitalniknihovna.cz, 2026-10-27 16:20 UTC, as seen on the source library
(NGINX log and Solr `logs` core):

| Request on the source | Count | Time span | p50 / max |
| --- | ---: | --- | ---: |
| forwarded tiles | 33 | 16:20:24 – 16:20:34 | 711 ms / 2,057 ms |
| forwarded `info.json` | **34** | 16:20:22 – 16:20:34 | 924 ms / 3,019 ms |
| access-log records (statistics "views") | **34** | 16:20:22 – 16:20:34 | — |
| distinct HTTP sessions created | 34 | | |

The same page opened through `digitalniknihovna.cz`, which loads tiles from the source directly, cost **1** `info.json` for 28 tiles.

An ordinary A5 book page (model `page` in a monograph, owned only by MZK) opened once through the CDK at 16:32 UTC:

| Request on the source | Count | Time span | p50 / max |
| --- | ---: | --- | ---: |
| forwarded tiles | 17 (16 probed) | 16:32:27 – 16:32:34 | 1,295 ms / 2,553 ms |
| forwarded `info.json` = recorded views | **17** | 16:32:25 – 16:32:33 | 1,441 ms / 2,389 ms |

An A4 periodical page (in MZK and NKP, requested through MZK) opened once through the CDK at 16:35 UTC produced 33 forwarded
tiles, all probed, and **34** forwarded `info.json` within 10 seconds.

| One open through the CDK | Map page | A4 periodical page | A5 book page |
| --- | ---: | ---: | ---: |
| forwarded tiles (probed) | 33 (33) | 33 (33) | 17 (16) |
| forwarded `info.json` = views recorded in source statistics | **34** | **34** | **17** |
| views a direct open records | 1 | 1 | 1 |

For the map page the Solr `logs` core held exactly 34 records, matching the 34 forwarded `info.json` in the NGINX log. For the
other two, the record count follows from the code (every successful forwarded `info.json` calls `reportAccess`).

The pattern does not depend on the document type; the number of views grows with the number of tiles the viewer loads.

The timeline is consistent: a batch of `info.json` requests, then the tiles that follow them, repeated as the reader zooms.

## Cause

Kramerius `master` at `560676c`:

- `IiifServlet` in `cdk.server.mode` (lines 144–155) probes `…/forward/iiif/{pid}/info.json` on the source before it proxies
  most of the tiles a deep-zoom viewer requests. In the map test
  **33 of 33** tiles were probed.
- Nothing caches the probe result, so each such tile probes again, even milliseconds after the previous one for the same image.
- Each probe is a full `CDKIIIFResource.iiifManifest` on the source: `reportAccess` (a statistics record with
  FOXML and Solr reads and a Solr write), the RELS-EXT image-server URL and an image-server `info.json` call. The probe carries
  no session cookie, so the source's `ExtAuthFilter` also creates a new HTTP session for every probe.

## Evidence and frequency

- The controlled test above (one reader, one page, one public licence).
- Across all traffic on 2026-10-27, forwarded `info.json` averaged ~18k per 6 hours, and 76% of them arrived within 10 s of a
  previous one for the same PID. That is consistent with this per-tile pattern being the norm, not specific to maps.
- The A4 and A5 book page tests confirm it is not specific to maps: 34 and 17 views for one open. A first A4 attempt was
  inconclusive because the page was not readable under the source's licences: the source answered the single `info.json` with
  403 and no tiles followed.

### Since when

Forwarded IIIF requests from the CDK per day on the source (NGINX access log, last 90 days, 2026-07-29 – 2026-10-27):

| Period | Forwarded `info.json` / day | Distinct images / day | `info.json` per image and day |
| --- | ---: | ---: | ---: |
| 2026-07-29 – 2026-09-03 | 1 – 809 | 1 – 776 | **1.0 – 3.5** |
| 2026-09-04 – 2026-09-16 | 28 – 2,715 | 1 – 75 | **11 – 48** |
| 2026-09-17 – 2026-10-27 | 13,010 – 124,392 | 1,023 – 27,714 | **3.9 – 12.7** |

- **The per-tile probing started on 2026-09-04.** Before that day the CDK asked for about one `info.json` per image; from that
  day on it asks for one per probed tile.
- **It matches the commit that added the probe.** `c2a05c0fb` "IIIF resource" (2026-09-04 08:04 +0200) added `probeInfoJson`
  to `IiifServlet`'s CDK path, and bumped `gradle.properties` from 7.2.2.1 to 7.2.2.2.
  The CDK therefore ran a 7.2.2.2 pre-release build from 2026-09-04, two weeks before the
  [v7.2.2.2 tag](https://github.com/ceskaexpedice/kramerius/releases/tag/v7.2.2.2) (2026-09-17). Every release since
  (v7.2.2.2, v7.2.2.3, v7.2.2.4) contains it; v7.2.2.1 (2026-09-03) and earlier do not.
- **From 2026-09-17, the v7.2.2.2 release day, forwarded traffic grew about 30×** (from hundreds to tens of thousands of
  `info.json` a day), with the probing already in place. Why the volume grew that day is not known from the source side.
- From 2026-09-17 to 2026-10-27 the source recorded **2.22 million** forwarded `info.json`, each a statistics record, for about
  **311 thousand** image-days. That is about **7×** more views than distinct images. The ratio per day is lower than the 17–34
  per single open above, because readers who open the same image again on the same day count only once in "distinct images".
- Statistics of CDK traffic from 2026-09-04 onward are inflated. Earlier data is not affected by this bug.

## Impact

- **Statistics (the main harm):** each image opened through the CDK is counted as many views on the source: 34 for the map,
  17 for an A5 page. Any usage report built from the `logs` core (views per document, per licence, per period) over-counts CDK
  traffic by roughly the number of tiles each reader loads, and the factor varies with image size and zooming, so the
  numbers cannot simply be divided back.
- **Latency for CDK readers:** each probed tile waits for a probe that took 0.6–3.0 s in the test.
- **Source load:** one access-log write and one image-server call per probed tile, plus a new HTTP session
  per probe. This adds to [PS-001](../perf-simple/PS-001-forward-resource-graph-per-request.md) and
  [PS-002](../perf-simple/PS-002-rights-check-refetches-solr-doc.md) on every probe.
- It affects every source library behind the CDK.

## Fix

Change how the CDK uses the probe:

1. **Probe once per image, not per tile.** Cache the probe result in the CDK for a short time (e.g. 60 s) per
   (source, PID, reader context). A reader's tile burst for one image then costs one probe.
2. **Mark probes** (e.g. header `X-CDK-Probe: 1`) and have the source's `iiifManifest` skip `reportAccess` for them, so
   statistics count image opens, not tiles.

Step 1 alone takes the test case from 34 probes to 1–2. Step 2 fixes statistics even where a probe remains.

## Test

- Open the same map page through the CDK: forwarded `info.json` per image open drops from 34 to ≤ 2, and the `logs` core gets
  one record per open.
- A reader without access to a protected document is still refused, both on the first open and after the cache expires.
- Unit test for the probe cache key: different readers or licences for the same PID never share a result.

## Missing upstream

[kramerius#1362](https://github.com/ceskaexpedice/kramerius/issues/1362) reports several view records for one image opened
through the CDK, and looks for the cause in statistics. Missing there:

- **Cause, in the CDK:** in `cdk.server.mode`, `IiifServlet` calls `…/forward/iiif/{pid}/info.json` on the source library
  (`probeInfoJson`) before most tiles of normal viewing. The probe result
  is not cached, so each such tile is one `info.json` at the source, one `reportAccess` and one record in `logs`.
- **Measured at MZK (NGINX):** one map opened through the CDK = 34 `info.json` and 34 `logs` records; an A5 book page = 17;
  the same page opened directly = 1. It started on **2026-09-04**, the day of commit `c2a05c0fb` ("IIIF resource"), which
  added `probeInfoJson` (released in 7.2.2.2); before that, about 1 `info.json` per image. From 2026-09-17 to 2026-10-27:
  2.22 million records for about 311 thousand image-days at MZK.
- **Fix:** (1) cache the probe result in the CDK for a short time per (source, PID, reader context); (2) mark the probe
  with a header (e.g. `X-CDK-Probe: 1`) and skip `reportAccess` for it at the source. Statistics since 2026-09-04 are
  inflated for CDK visits and cannot simply be recomputed, because the count depends on image size and zooming.

## Related

- [kramerius#1362](https://github.com/ceskaexpedice/kramerius/issues/1362) (open since 2026-10-06): another library reports the
  same symptom, 59 log records for one map opened through ČDK, roughly one per `info.json`. No cause was posted there yet.
- [PM-003](../perf-medium/PM-003-batched-access-log-writer.md): access logging cost, paid once per probe today.
