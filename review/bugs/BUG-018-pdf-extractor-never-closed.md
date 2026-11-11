---
id: BUG-018
former_id: BUG-029
category: bug
title: Indexing a PDF object never deletes its temp copy of the PDF, so a job that indexes many PDFs fills the worker's /tmp until its JVM exits
area: indexing
severity: medium
effort: XS               # make PdfExtractor closeable, try-with-resources in Indexer, delete the temp file on close
use_cases: [indexing]
review_ref: [B5]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1374
checked: [source, production]
checked_how: "Read PdfExtractor use at Kramerius af7209c; MZK worker /tmp sampled during one reindex 2026-10-28"
checked_on: 2026-11-10
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-018 — Indexing a PDF object never deletes its temp copy of the PDF, so a job that indexes many PDFs fills the worker's /tmp until its JVM exits

> **In one sentence:** for every object whose IMG_FULL is a PDF, the indexer copies the PDF to a temp file and opens it with
> PDFBox, but never closes it or deletes the copy; the copy is only marked `deleteOnExit`, so one indexing job over many PDF
> objects keeps a copy of every PDF in `/tmp` until the job's JVM ends.

## Upstream issue

[kramerius#1374](https://github.com/ceskaexpedice/kramerius/issues/1374) "Indexácia PDF objektov nemaže dočasné kópie PDF,
takže reindexácia stromu s mnohými PDF plní `/tmp` workera až do konca jobu", opened by MZK on 2026-11-10 from this entry:
cause, the `/tmp` measurement of 2026-10-28, since when (`c083bc6ee`, `v7.0`) and the fix (`Closeable`, delete the copy in
`close()`, try-with-resources). It deliberately leaves out heap and file-descriptor growth (see Impact).

## Symptom

During a reindex of a tree or model with many PDF objects, `/tmp` in the worker pod fills with `uuid_….pdf` copies, one per
PDF, until the job ends (measured below). For a large job, the likely outcome is a full ephemeral disk on the worker node.

## Cause

Kramerius `master` at `af7209cd5`, `processes/search-index/.../indexer/execution/`:

- `PdfExtractor` (`PdfExtractor.java:25–39`) creates a temp file (`File.createTempFile(pid, ".pdf")`), marks it
  `deleteOnExit`, copies the IMG_FULL stream into it, and loads it with `PDDocument.load(File, password)` (PDFBox 2.0.32). That
  `PDDocument` keeps the file open and holds the parsed objects in heap until `close()`.
- `PdfExtractor` has no `close()`. The old `finalize()` that closed the document is commented out (`:65–68`).
- `Indexer.indexPagesFromPdf` (`Indexer.java:364–380`) creates one `PdfExtractor` per object with
  `ds.img_full.mime = application/pdf` (`:322–323`), reads the pages, and drops it without closing.
- `deleteOnExit` runs only when the JVM shuts down (normal exit or SIGTERM). A JVM ended by SIGKILL (OOM kill) leaves every
  copy until the container is replaced. If `PDDocument.load` throws (corrupt or encrypted PDF), the copy is also kept until exit.

Each job runs in its own plugin JVM, so the leak is bounded by one job, and a single-object reindex is harmless. A job that
indexes a whole tree or model reaches every PDF in it in one JVM.

## Evidence and frequency

**Measured at MZK on 2026-10-28.** One `TREE_AND_FOSTER_TREES` reindex of a tree with a few hundred PDF objects, picked up
by `worker-default-3`. The worker's `/tmp`, sampled every ~20 s:

| Time (UTC) | `*.pdf` temp files | Size |
| --- | --- | --- |
| 13:56:54 | 25 | 32 MiB |
| 13:57:36 | 158 | 156 MiB |
| 13:58:17 | 241 | 802 MiB |
| 13:59:00 | 310 | 1,629 MiB |
| 13:59:41 | 411 | 1,825 MiB |

The count only grew while the job ran, about one full copy per PDF processed, and dropped to 0 when the job's JVM exited
normally (`deleteOnExit`). Open file descriptors and heap were not sampled: plugin JVMs start as `java @<args file>`, so the
sampler did not recognize the process.

- MZK has **13,832** objects whose IMG_FULL is a PDF (public search API, 2026-10-28): 10,571 `article`, 2,320 `monograph`,
  940 `periodicalitem`, 1 `supplement`. At the measured ~4.4 MiB per copy, a model-wide reindex of articles would hold
  roughly 45 GB of copies in the worker's `/tmp` before the JVM exits.
- A job JVM ended by SIGKILL (OOM kill) never runs `deleteOnExit`; its copies stay until the container is replaced.

## Impact

- **Worker node disk:** temp copies of every PDF in the job sit in the container's writable layer until the JVM exits
  (`deleteOnExit` runs on a normal exit and on SIGTERM, not on SIGKILL such as an OOM kill). A model-wide reindex of
  articles would need about 45 GB.
- **Heap and file descriptors, not established:** the extractor is a local variable, so once it is dropped the GC can
  collect the `PDDocument` and the JVM can release its file handle. Growth of heap or open files was not measured and is not
  claimed.

## Fix

1. Make `PdfExtractor` implement `Closeable`: close the `PDDocument` and delete the temp file in `close()`. Drop
   `deleteOnExit`.
2. In `Indexer.indexPagesFromPdf`, use try-with-resources around the extractor.
3. In the constructor, delete the temp file if `PDDocument.load` throws.
4. Optional: load from the stream with `MemoryUsageSetting.setupTempFileOnly()` instead of a manual copy, so PDFBox manages
   and removes its own scratch file.

## Test

- Unit test: index the same small PDF fixture 200 times through `indexPagesFromPdf` with a stub Solr indexer. Before the fix,
  the count of `*.pdf` files in a test temp directory (`java.io.tmpdir` pointed at it) grows by 200; after the fix it returns
  to 0, and the number of open file descriptors of the test JVM does not grow.
- Unit test: a corrupt PDF fixture; the constructor must throw `IOException` and leave no temp file.

## Related

- [BUG-003](BUG-003-model-reindex-hides-page-errors.md): a model-wide reindex that fails partway also reports the title as
  indexed.
- [BUG-013](BUG-013-ocr-dropped-on-invalid-xml-char.md): another per-object indexing failure path.
