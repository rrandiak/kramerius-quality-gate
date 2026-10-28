---
id: QOL-006
former_id: BUG-026
category: quality-of-life
title: web.xml still declares the deleted servlets behind /fullThumb and /pdf, so Tomcat logs ClassNotFoundException and those URLs cannot work
area: modularization
severity: low
effort: XS               # delete two <servlet> and two <servlet-mapping> entries from web.xml
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read web.xml at Kramerius 560676c (servlets deleted in cbe1af5); 7 days of MZK Tomcat logs"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# QOL-006 — web.xml still declares the deleted servlets behind /fullThumb and /pdf, so Tomcat logs ClassNotFoundException and those URLs cannot work

> **In one sentence:** `FullThumbnailImageServlet` and `GeneratePDFServlet` were removed from the code, but `web.xml` still
> declares and maps them, so Tomcat logs a `ClassNotFoundException` for each of them, and requests to the old
> `/search/fullThumb` and `/search/pdf` URLs fail instead of getting a clean 404 or 410.

## Symptom

Public and curator Tomcat logs contain `ClassNotFoundException: cz.incad.Kramerius.FullThumbnailImageServlet` and
`…GeneratePDFServlet` with no Kramerius code in the stack. Clients calling the old URLs get an error instead of a clean
"not found" (the exact status was not checked).

## Cause

Kramerius `origin/master` at `560676c`:

- `search/web/WEB-INF/web.xml:190–198` declares the servlets `fullThumb` (`cz.incad.Kramerius.FullThumbnailImageServlet`) and
  `pdf` (`cz.incad.Kramerius.GeneratePDFServlet`), mapped to `/fullThumb` (`:346–347`) and `/pdf` (`:358–359`).
- The classes are gone: `FullThumbnailImageServlet.java` was deleted in `cbe1af55f` (2025-10-24, "delete obsolete processes"),
  `GeneratePDFServlet.java` in `522cb0adf` (2026-02-12, "VISK pdf support"). The `web.xml` entries were left in place.
- Tomcat cannot load either class. It logs the failure when it processes the declared servlets (the identical counts below
  suggest this happens together for both, once per web app start, rather than per request), and a request to `/fullThumb`
  or `/pdf` cannot be served.

## Evidence and frequency

MZK production, Tomcat logs of the last 7 days to 2026-10-28 (class names and code locations only):

| Missing class | `kramerius-public` | `kramerius-curator` |
| --- | ---: | ---: |
| `FullThumbnailImageServlet` | 18 | 13 |
| `GeneratePDFServlet` | 18 | 13 |

These were the only `ClassNotFoundException`s in all Kramerius, curator, worker and process-manager pods. Both classes have
exactly the same count per pod type, so the lines most likely come in pairs, per web app start; how many requests hit the old
URLs was not checked.

## Impact

Low: noise in the log on every start, which hides real class-loading problems in log sweeps, and old links to
`/fullThumb` or `/pdf` get an error instead of a clean "gone".

## Fix

Delete the two `<servlet>` and two `<servlet-mapping>` entries from `web.xml`. Optionally answer the old URLs with 410 Gone,
or redirect `/fullThumb` to the v7 thumbnail endpoint if old links should keep working.

## Test

- After the change, `GET /search/fullThumb` and `GET /search/pdf` return 404 (or the chosen 410 or redirect), and no
  `ClassNotFoundException` appears in the log.
- A build check that every `<servlet-class>` in `web.xml` exists in the WAR would catch this class of leftover.

## Related

- [PS-004](../perf-simple/PS-004-desirable-table-written-never-read.md): another leftover of the K5 web front end.
