---
id: BUG-018
former_id: BUG-029
category: bug
title: Indexing a PDF object never closes the PDF, so a job that indexes many PDFs keeps every document, file handle and temp copy until its JVM exits
area: indexing
severity: medium
effort: XS               # make PdfExtractor closeable, try-with-resources in Indexer, delete the temp file on close
use_cases: [indexing]
review_ref: [B5]
upstream: null
checked: [source, production]
checked_how: "Read PdfExtractor use at Kramerius af7209c; MZK worker /tmp sampled during one reindex 2026-10-28"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-018 — Indexing a PDF object never closes the PDF, so a job that indexes many PDFs keeps every document, file handle and temp copy until its JVM exits

> **In one sentence:** for every object whose IMG_FULL is a PDF, the indexer copies the PDF to a temp file and opens it with
> PDFBox, but never closes it or deletes the copy, so one indexing job over many PDF objects accumulates all of them in heap,
> open files and `/tmp` until the job's JVM ends, and a killed job leaves the copies behind.

## Symptom

During a reindex of a tree or model with many PDF objects, `/tmp` in the worker pod fills with `uuid_….pdf` copies, one per
PDF, until the job ends (measured below); the plugin JVM's heap and open file count grow with them. For a large job,
possible outcomes are an `OutOfMemoryError` in the plugin JVM, a full ephemeral disk on the worker node, or "Too many open
files".

## Cause

Kramerius `master` at `af7209cd5`, `processes/search-index/.../indexer/execution/`:

- `PdfExtractor` (`PdfExtractor.java:25–39`) creates a temp file (`File.createTempFile(pid, ".pdf")`), marks it
  `deleteOnExit`, copies the IMG_FULL stream into it, and loads it with `PDDocument.load(File, password)` (PDFBox 2.0.32). That
  `PDDocument` keeps the file open and holds the parsed objects in heap until `close()`.
- `PdfExtractor` has no `close()`. The old `finalize()` that closed the document is commented out (`:65–68`).
- `Indexer.indexPagesFromPdf` (`Indexer.java:364–380`) creates one `PdfExtractor` per object with
  `ds.img_full.mime = application/pdf` (`:322–323`), reads the pages, and drops it without closing.
- `deleteOnExit` runs only when the JVM exits normally. A job JVM that is killed (admin kill, OOM kill, pod restart) leaves
  every copy. If `PDDocument.load` throws (corrupt or encrypted PDF), the copy is also kept until exit.

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
sampler did not recognize the process. Each unclosed `PDDocument` keeps its file open, so descriptors grow with the files
(source, not measured).

- MZK has **13,832** objects whose IMG_FULL is a PDF (public search API, 2026-10-28): 10,571 `article`, 2,320 `monograph`,
  940 `periodicalitem`, 1 `supplement`. At the measured ~4.4 MiB per copy, a model-wide reindex of articles would hold
  roughly 45 GB of copies in the worker's `/tmp` before the JVM exits, plus 10.5k open documents in one heap.
- A job JVM that is killed, or dies of OOM, never runs `deleteOnExit`; its copies stay until the pod is restarted.

## Impact

- **Indexing jobs:** a large PDF reindex can fail with OOM or "Too many open files" partway through, after indexing only part
  of the tree. Pages that were not reached stay unindexed.
- **Worker node disk:** temp copies of every PDF in the job sit in the container's writable layer until the JVM exits, and
  for good after a kill, until the pod restarts.

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
