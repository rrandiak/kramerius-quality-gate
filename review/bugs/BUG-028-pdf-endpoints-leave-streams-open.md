---
id: BUG-028
former_id: null
category: bug
title: The PDF endpoints never close the three output streams they open per request, and leave the rendered file behind when generation fails
area: async
severity: low
effort: XS               # try-with-resources and one delete in AbstractPDFResource
touches: [kramerius/rest (client v7 pdf)]
contracts: []
data_migration: false
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read AbstractPDFResource, PDFResource and AsyncPDFResource at Kramerius 560676c; one MZK public pod 2026-10-28 had no leftover PDF temp files at one instant"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-028 — The PDF endpoints never close the three output streams they open per request, and leave the rendered file behind when generation fails

> **In one sentence:** every PDF selection or parent request opens three `FileOutputStream`s on temporary files and
> closes none of them, so their file descriptors (and the disk space of the already deleted temporary files) are held
> until garbage collection, and a failure after the result file is created leaves that file in the temp directory.

## Symptom

Tomcat's temp directory on a public pod can collect `rendered*pdf` files after failed PDF requests, and the JVM holds
open descriptors to deleted `body*pdf` / `head*pdf` files (visible as `(deleted)` in `/proc/<pid>/fd`) until a GC runs.

## Cause

Kramerius `560676c`, `rest/.../apiNew/client/v70/pdf/AbstractPDFResource.java`, in both `selection` (lines 117–147) and
`parent` (lines 165–202):

- `new FileOutputStream(...)` for the body (lines 122, 180), the first page (125, 183) and the merged result (141, 194):
  none is closed. `mergeToOutput` (232–238) writes to the result stream but does not close it either.
- The `finally` blocks (146, 201) delete the body and first-page files, but their streams are still open, so on Linux the
  space is released only when the stream is collected.
- The result file `rendered*pdf` (141, 194) is created inside the `try` and is not deleted when the merge or anything
  after it throws. After a successful request the caller deletes it once streamed (`PDFResource.java:306`, `:407`,
  `:495`).

Not a problem at this revision: `PDFExlusiveGenerateSupport` keeps prepared PDFs in a static map with no expiry
(`PDFExlusiveGenerateSupport.java:30–39`), but the asynchronous endpoints that would fill it are commented out
(`AsyncPDFResource.java:69` onward; only `handle` is active), so nothing puts files into it.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

On 2026-10-28 one public pod had no leftover PDF temp files at one instant and 1,524 open descriptors, without a baseline
or attribution ([bug hunt 2](../raw/26-bug-hunt-2.md)). Upstream reports other PDF temp-file leaks in different code:
[kramerius#1358](https://github.com/ceskaexpedice/kramerius/issues/1358) (JPG files from `SimplePDFServiceImpl` after an
exception) and [kramerius#1290](https://github.com/ceskaexpedice/kramerius/issues/1290) (ALTO temp files).

## Impact

Descriptors and temp disk space grow with PDF traffic between garbage collections; failed requests leave result files
until someone cleans the temp directory. With enough PDF traffic and little GC pressure this can reach the descriptor
limit or fill the temp volume.

## Fix

Open all three streams in try-with-resources, close the result stream before returning the file, and delete the result
file in a `catch` when generation fails. Delete the unused `PDFExlusiveGenerateSupport` map, or give it an expiry if the
asynchronous endpoints come back.

## Test

Generate a PDF selection with a stub first-page renderer that throws after the result file is created: before the fix the
`rendered*pdf` file remains and three descriptors stay open (count `/proc/self/fd` in the test); after it, no file and no
extra descriptor remain.

## Missing upstream

Not reported. An issue for `ceskaexpedice/kramerius` should state:

- **Finding:** `AbstractPDFResource.selection` and `parent` open three `FileOutputStream`s per request (lines 122, 125,
  141 and 180, 183, 194) and close none; the result file is not deleted when generation fails. Related but different
  leaks: #1358, #1290.
- **Fix:** try-with-resources for the streams, delete the result file on failure.

## Related

- [BUG-018](BUG-018-pdf-extractor-never-closed.md): the PDF leak on the indexing side.
- [BUG-015](BUG-015-pdf-font-scan-per-request.md): another per-request cost in the same PDF path.
