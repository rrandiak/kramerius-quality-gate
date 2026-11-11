---
id: BUG-026
former_id: BUG-027
category: bug
title: The IIIF endpoint answers 500 and logs SEVERE for objects that have no IIIF image, instead of 404
area: storage
severity: low
effort: XS               # return 404 in one branch of IiifServlet; align items/info with IIIF on the K4 cache marker
use_cases: [image-open]
review_ref: []
upstream: https://github.com/ceskaexpedice/kramerius/issues/1383
checked: [source, production]
checked_how: "Read the IIIF resource at Kramerius 560676c and 3c8bacca (7.2.2.4, same on master); MZK public catalina logs 2026-10-12 to 2026-11-11 (1,582 lines, 740 objects) checked against items info"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-026 — The IIIF endpoint answers 500 and logs SEVERE for objects that have no IIIF image, instead of 404

> **In one sentence:** when a client asks `/search/iiif/{pid}/…` for an object without a `tiles-url` in RELS-EXT (a book,
> an article, or a page that only has a JPEG), Kramerius logs `No iip url for <pid>` as SEVERE and answers 500, although
> "this object has no IIIF image" is a normal 404.

## Upstream issue

[kramerius#1383](https://github.com/ceskaexpedice/kramerius/issues/1383) "IIIF vracia 500 pre objekty, ktoré IIIF obrázok nemajú, namiesto 404", opened by MZK on
2026-11-11 from this entry: the `null` branch of `IiifServlet` at 7.2.2.4 (`3c8bacca`), the 30-day MZK numbers (1,582 answers,
740 objects, 739 without an IIIF image), the difference from #1198, since when (`c183a57dd`, `v7.0.36`) and the fix (404,
log at most at FINE). The K4-marker mismatch (fix item 2) is not in the issue.

## Symptom

`No iip url for uuid:…` lines in the public Tomcat log, and 500 answers on direct IIIF URLs for objects that simply have no
tiles.

## Cause

Kramerius `origin/master` at `560676c`:

- `IiifServlet` resolves the image server URL with `IIIFUtils.iiifImageEndpoint` (`search/src/java/cz/incad/Kramerius/imaging/IiifServlet.java:172`),
  which returns `null` when RELS-EXT has no `tiles-url`, or when it holds the old K4 marker `kramerius4://deepZoomCache`
  (`shared/common/.../iiif/IIIFUtils.java:33–40`).
- On `null`, the servlet logs SEVERE and sends 500 (`IiifServlet.java:196–198`).
- **Mismatch for the K4 marker:** `items/{pid}/info` reports `image.type = "tiles"` for any non-null `tiles-url`, including the
  K4 marker, unless `deepZoom.cachedir.disable` is set (`ExtractDataInfoUtils.java:46–49`, default `false`). A client is told
  the object has tiles and then gets 500 from IIIF.

## Evidence and frequency

**30 days, 2026-10-12 to 2026-11-11** (Tomcat logs of both public pods, `catalina.*.log`): 1,582 `No iip url` lines for 740
objects. `image.type` from `items/{pid}/info`: `image/jpeg` 628, `none` 111, `tiles` 1. So 739 of 740 were requests for
objects without an IIIF image; all got 500. At 7.2.2.4 (`3c8bacca`) the branch is `IiifServlet.java:216–218`; the explicit
500 came with `c183a57dd` (2024-07-29, `v7.0.36`), before that the same case was a `NullPointerException`, also 500.
Not the same as kramerius#1198 (same log line, but there the object had a `tiles-url` and its parsing failed).

Earlier sample, MZK production, public pods' logs of the last 7 days to 2026-10-28: 100 `No iip url` lines for 69 distinct objects. Model and
`image.type` from the public API for each object (counts only):

| Model | `image.type` from `items/{pid}/info` | Objects |
| --- | --- | ---: |
| page | `image/jpeg` (full image, no tiles) | 36 |
| monographunit, article, monograph, map, graphic, sheetmusic, periodicalvolume | `none` | 32 |
| page | `tiles` (IIIF still refuses it) | 1 |

So 68 of 69 are requests for objects that have no IIIF image; one page has a `tiles-url` that IIIF cannot use, most likely the
K4 cache marker.

## Impact

Low. Clients get a server error instead of "not found" and cannot fall back cleanly (e.g. to `/image` for JPEG-only pages);
the SEVERE lines add noise to error monitoring. The one mismatched page cannot be shown through IIIF.

## Fix

1. In `IiifServlet`, answer **404** when `iiifImageEndpoint` returns `null`, and log at FINE or INFO.
2. Make `items/{pid}/info` and IIIF agree on the K4 marker: either report it as not tiles (as `deepZoom.cachedir.disable=true`
   does) or let IIIF serve it. Then fix the objects that still carry the marker (one found at MZK).

## Test

- `GET /search/iiif/<pid of a monograph>/info.json` returns 404, with no SEVERE log line.
- For an object whose `tiles-url` is the K4 marker, `items/{pid}/info` and IIIF give consistent answers.

## Related

- [BUG-017](BUG-017-search-solr-400-returned-as-500.md): another client error reported as 500.
- [BUG-016](BUG-016-export-fails-on-file-referenced-streams.md) and [KB-012](../known-bugs/KB-012-internalize-file-referenced-streams.md):
  other objects whose image or text data is not where the API expects it.
