---
id: PS-004
former_id: BUG-025
category: perf-simple
title: Every PDF page and Zoomify request writes a "most desirable" row that nothing reads, after an extra RELS-EXT read
area: storage
severity: low
effort: XS               # remove the saveAccess calls (or the MostDesirable binding); optional drop of the table
use_cases: [image-open, storage]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read MostDesirable at Kramerius 560676c; MZK kramerius DB counts 2026-10-28"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# PS-004 — Every PDF page and Zoomify request writes a "most desirable" row that nothing reads, after an extra RELS-EXT read

> **In one sentence:** Kramerius 7 still records every PDF page and Zoomify access in the `desirable` table for the old
> "most desirable" home tab, which nothing reads any more, so each page costs a RELS-EXT read and a database insert for
> nothing, and the table grows by about 150,000–225,000 rows a month without ever being cleaned.

## Symptom

The `desirable` table in the `kramerius` database grows steadily (126 MB at MZK after five months), and PDF generation does one
extra repository read and one insert per page. No API or screen shows the data.

## Cause

Kramerius `origin/master` at `560676c`:

- **Writers.** `MostDesirableImpl.saveAccess` (`shared/common/.../impl/MostDesirableImpl.java:71–81`) reads the object's model
  from RELS-EXT through the repository (`akubraRepository.re().getModel(uuid)`) and inserts `(uuid, access, model)`. It is
  called for every PID of a PDF request (`AbstractPDFResource.java:129`, `:174`; `PDFResource.java:517`) and on Zoomify
  access (`ZoomifyHelper.java:78`, `ZoomifyServlet.java:169`).
- **Reader.** `MostDesirable.getMostDesirable` (the K5 "Nejžádanější" / most requested home tab) has no caller anywhere in
  the repository.
- **No cleanup.** Nothing deletes old rows; `most.mostdesirable.numberofdays` only limited the (now unused) read.

## Evidence and frequency

MZK production, `kramerius` database, read-only query on 2026-10-28:

| Measure | Value |
| --- | --- |
| Rows / distinct objects | 981,937 / 273,990 |
| First / last row | 2026-05-18 (the current production deploy) / 2026-10-27 |
| Rows per month (Jun–Oct) | 149k, 226k, 215k, 152k, 145k |
| Model | `page` 981,901; `monograph` 35; `periodicalitem` 1 |
| Size | 126 MB |

Almost all rows are pages, so they come from PDF generation (one row per page in the selection or book).

## Impact

- **PDF latency and load:** one RELS-EXT read and one insert per page, about 5,000–7,000 a day at MZK. Small per page, but
  multiplied by every page of a generated PDF.
- **Storage:** about 25 MB a month, growing without limit.
- No functional effect: removing it changes nothing a user can see.

## Fix

Remove the `saveAccess` calls from the PDF and Zoomify paths (or the `MostDesirable` interface, implementation and Guice
binding together), and stop creating the table in `MostDesirableDbInitializer`. Installations can then drop `desirable`.
If someone still wants "most requested" lists, the access log in the Solr `logs` core already holds the same events.

## Test

- Generate a PDF of a few pages: no insert into `desirable` and no RELS-EXT read for `MostDesirable` (span or log check).
- Production after the change: the row count of `desirable` stops growing.

## Related

- [BUG-015](../bugs/BUG-015-pdf-font-scan-per-request.md): another per-request cost in PDF generation.
- [PM-003](../perf-medium/PM-003-batched-access-log-writer.md): the access log records the same reads, with enrichment.
