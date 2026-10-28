# PDF virtual pages versus scanned pages: indexing cost per page

A natural experiment on MZK production, 2026-10-28. When an object's IMG_FULL is a PDF, the indexer reads the PDF once and
indexes each PDF page as a "virtual page" without reading any per-page object from the repository. A scanned book indexes
each page as its own repository object. Indexing two monographs of the same page count, one of each kind, shows how much of a
normal page's indexing time is per-page repository work. It is one measurement on one pair, not a benchmark.

## What differs between the two paths

Kramerius `master` at `af7209cd5`, `processes/search-index`:

| Per page | Scanned page (own object) | PDF virtual page |
| --- | --- | --- |
| Node build (`RepositoryNodeManager.getKrameriusNode`) | yes | no, reuses the parent's node (`SolrInputBuilder.processPageFromPdf`, `:67–172`) |
| FOXML, RELS-EXT, OCR/ALTO and metadata reads (Akubra, NFS) | yes | no; the PDF is read once for the whole object (`Indexer.indexPagesFromPdf`, `:364–381`) |
| Processing-index lookups | yes | no |
| Text | OCR datastream | PDFBox `PDFTextStripper` on one page of the in-memory document |
| Solr document | built from the page's own FOXML and metadata | built from the parent's node: PID `<parent>_<n>`, model `page`, page index, text; no metadata of its own |
| Solr add | one HTTP request per page | one HTTP request per page (same call, `indexFromXmlString`) |

So the virtual page shows roughly what a page costs **without** the per-page repository work, with PDFBox extraction added.
Both paths send one Solr request per page, so this says nothing about batching Solr writes
([PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md)).

## Run of 2026-10-28

| Run | Object | Reindex type | Objects indexed | Duration | Per page |
| --- | --- | --- | --- | --- | --- |
| A, PDF | `uuid:7a3aece9-f977-4d79-b7f8-c21ba2119ff2` | object | 749 (748 virtual pages + monograph) | 25 s | **~33 ms** |
| B, scanned | `uuid:960a2b80-f6e6-11e8-bc37-005056827e51` | tree | 749 (748 pages + monograph) | 116 s | **~155 ms** |

Durations are the indexer's `records processing duration` (1 s resolution). B ran from about 14:10:33 to 14:12:29 UTC and
A from about 14:10:43 to 14:11:08 UTC, on different worker pods, so the runs overlapped. B's ~155 ms per page matches the
~160 ms per page from worker traces on 2026-10-27 ([PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md)).
Both were first runs of the day for these objects; the NFS cache state was not controlled.

## Reading

- A scanned page took about **4.7×** as long as a PDF virtual page, about **120 ms** more per page.
- That difference is close to the traced per-page node build (p50 ~111 ms) plus Akubra reads (~21 ms) on 2026-10-27, which
  supports the trace split: per-page repository and processing-index work is most of a normal page's indexing time.
- A's ~33 ms is not a floor that read-once plus prefetch ([PM-001](../perf-medium/PM-001-read-once-then-prefetch.md))
  could reach for real pages: virtual pages have no metadata of their own and reuse the parent's node, while real pages
  still need their own FOXML and node. It bounds what the remaining work (text extraction, document build, one Solr add)
  costs per page.
- Not separated: PDFBox extraction versus Solr add within A; node build versus NFS reads within B.

## How to repeat it

1. Pick a PDF monograph with N virtual pages (N about 500–1,500; avoid the 3,500+ page PDFs, which make one very large
   in-memory document). Virtual pages have PIDs `<parent>_<n>`, so the public search API can count them per parent:

   ```
   GET /search/api/client/v7.0/search?q=model:page AND own_parent.model:monograph AND pid:*_*
       &rows=0&facet=true&facet.field=own_parent.pid&facet.limit=15&facet.offset=100&facet.mincount=100
   ```

   Raise or lower `facet.offset` until the counts are near N.
2. Pick a scanned monograph with OCR and about the same page count:

   ```
   GET /search/api/client/v7.0/search?q=model:monograph AND count_page:[N-50 TO N+50] AND has_text_ocr_content:true
       &fl=pid,count_page&sort=count_page desc&rows=15
   ```

3. Outside peak hours, reindex the PDF monograph with type **object** (its virtual pages are rebuilt from the PDF inside
   that object's indexing) and the scanned monograph with type **tree**. Run them one after the other, not at the same time.
4. From each job's log take `objects indexed` and `records processing duration`. Per page = duration / objects indexed.
5. Optional: run both again right away. The second run reads more from the NFS cache; the change between first and second
   run shows how much of the scanned-page cost is NFS latency.

To compare with this run, reuse the two PIDs above.

## Related

- [BUG-018](../bugs/BUG-018-pdf-extractor-never-closed.md): the same PDF path keeps every PDF open and copied until the
  job ends; measured in an earlier run that day.
- [Benchmark handoff](19-benchmark-handoff.md): the controlled indexing workload this experiment approximates.
