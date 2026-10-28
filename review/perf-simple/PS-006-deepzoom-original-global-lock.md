---
id: PS-006
former_id: null
category: perf-simple
title: Reading a cached deep-zoom original holds one lock for the whole instance, so concurrent Zoomify and deep-zoom requests read and decode images one at a time
area: caching
impact: unknown          # only when a deep-zoom original cache exists; legacy routes had no traffic in one check
effort: XS               # drop synchronized from one method
touches: [kramerius/shared:common (imaging)]
contracts: []
data_migration: false
use_cases: [image-open]
review: [26-bug-hunt-2]
upstream: null
checked: [source, production]
checked_how: "Read FileSystemCacheServiceImpl, ImageModule and callers at Kramerius 560676c; warm 5-hour MZK window had no requests on the legacy image servlet routes"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-006 — Reading a cached deep-zoom original holds one lock for the whole instance, so concurrent Zoomify and deep-zoom requests read and decode images one at a time

> **In one sentence:** `FileSystemCacheServiceImpl.getDeepZoomOriginal` is `synchronized` on a Guice singleton and reads
> and decodes the whole JPEG from NFS inside the lock, so wherever deep-zoom originals are cached, every Zoomify,
> deep-zoom or full-image request that needs one waits for all the others.

## Today

Kramerius `560676c`:

- `ImageModule` binds `FileSystemCacheServiceImpl` as a singleton (`shared/common/.../imaging/guice/ImageModule.java:29–35`).
- `getDeepZoomOriginal` is `public synchronized` and, inside the lock, checks the cache folder, then reads and decodes the
  image with `KrameriusImageSupport.readImage(...)` (`shared/common/.../imaging/impl/FileSystemCacheServiceImpl.java:365–373`).
  The lock covers the NFS read and the JPEG decode of a full-size image, and it is the same lock for every object.
- Callers: the v7 client API's Zoomify path (`rest/.../client/v70/ZoomifyHelper.java:143`) and the legacy servlets
  (`search/.../imaging/ZoomifyServlet.java:318`, `DeepZoomServlet.java:252`, `FullImageServlet.java:134`).
- It applies only when a deep-zoom original was prepared in the local cache folder (`isDeepZoomOriginalPresent`);
  otherwise the method throws and the callers take another path.

**Seen at MZK:** a warm five-hour window on 2026-10-28 had no requests for the legacy image servlet routes
([bug hunt 2](../raw/26-bug-hunt-2.md#performance-follow-up-from-read-only-production-aggregates)). Whether MZK has a
deep-zoom original cache at all, and how much v7 Zoomify traffic reaches this method, was not checked.

## Idea

Remove `synchronized` from `getDeepZoomOriginal`: the method only reads an immutable file. If duplicate decoding of the
same image under load matters, coordinate per PID (a bounded map of in-flight loads), never with one lock for all objects.

## Expected gain

| Use case | Today | After (rough) | Confidence | Basis |
| --- | --- | --- | --- | --- |
| concurrent Zoomify / deep-zoom requests with cached originals | serialized per instance: N requests wait N × (NFS read + decode) | in parallel, limited by CPU and NFS | high for the mechanism, unknown for MZK | source |

No gain where no deep-zoom original cache exists.

## Pros

- One-word change; the read is of an immutable file.

## Cons and risks

- Without the lock, many concurrent decodes of large images can use more heap at once; a per-PID coordination or a
  bounded executor limits that if needed.

## Alternatives

1. **Do nothing.** Fine if the deep-zoom original cache is not used anywhere that matters.
2. **Drop the deep-zoom original cache** if IIIF has replaced it for all libraries.

## Effort

**Size: XS**, one method in one class.

| Part | Size | Why this size |
| --- | --- | --- |
| Remove the lock | XS | one keyword |
| Optional per-PID coordination | S | a small bounded map |

## How we would validate it

First check whether MZK (or any library) has a deep-zoom original cache and Zoomify traffic on the v7 route; if not, the
entry is cleanup only. Otherwise, a staging test with 10 concurrent Zoomify requests for different objects with cached
originals: the time to serve all of them should drop from about 10 single-request times to about one.

## Open questions

- Does any library still prepare deep-zoom originals, or is this cache dead with IIIF?
