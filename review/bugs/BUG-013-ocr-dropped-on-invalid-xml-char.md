---
id: BUG-013
former_id: BUG-008
category: bug
title: A page with one invalid control character in its OCR is indexed with no full text at all
area: indexing
severity: medium
effort: XS               # strip XML-invalid characters from OCR before building the Solr document
use_cases: [indexing, search]
review_ref: []
upstream: null
checked: [source]
checked_how: "Read the indexer at Kramerius 560676c; a code comment shows it happened; not counted at MZK"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-013 — A page with one invalid control character in its OCR is indexed with no full text at all

> **In one sentence:** the indexer turns each Solr document into an XML string and parses it back; if the OCR contains a
> single character that XML 1.0 does not allow, parsing fails and the indexer silently indexes the page again **without
> any OCR**, so the whole page disappears from full-text search.

## Symptom

A page whose OCR datastream has text is not found by full-text search for words that are clearly on it. Its Solr document has
no `text_ocr`. The worker log of the indexing job contains:

```
Reindexing without text_ocr after DocumentException: pid=uuid:…, model=page, originalOcrLength=…, error=…
  Character reference "&#6" is an invalid XML character.
```

## Cause

Kramerius `origin/master` at `560676c`, `processes/search-index/.../indexer/execution/Indexer.java`:

1. The OCR text is read and normalised: hyphenation at line ends is joined and every run of `\s` becomes one space
   (`normalizeWhitespacesForOcrText`, lines 390–400). `\s` covers tab, newline, vertical tab, form feed and carriage
   return. Other control characters (U+0000–U+0008, U+000E–U+001F) stay in the text.
2. `SolrInputBuilder` puts the text into a dom4j document, `asXML()` serialises it, and
   `SolrIndexAccess.indexFromXmlString` parses that string again with `SAXReader` (`SolrIndexAccess.java:109–137`). dom4j writes
   a control character as a character reference such as `&#6;`, and an XML 1.0 parser rejects it.
3. The indexer catches the `DocumentException` and indexes the page again with `""` as OCR (`Indexer.java:307–319`, the comment
   on line 308 quotes exactly this error). The page is counted as indexed; only a log line remains.

The XML round trip exists only to convert the dom4j document to a `SolrInputDocument`; Solr itself would accept the text
over javabin. One bad character therefore costs the entire page text.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source and code comment; the comment shows it happened in practice. Not yet counted at MZK.

Since 2026-10-27 the indexing JVMs send traces with a span on `SolrIndexAccess.indexFromXmlString` (chart 1.3.2). A failed call
ends with an error and `exception.type = org.dom4j.DocumentException`:

```sql
SELECT toDate(Timestamp) AS day, count() AS pages_without_ocr
FROM default.otel_traces
WHERE Timestamp >= now() - INTERVAL 7 DAY AND SpanName = 'SolrIndexAccess.indexFromXmlString' AND StatusCode = 'STATUS_CODE_ERROR'
GROUP BY day ORDER BY day
```

The collector's tail sampler keeps every trace that contains an error span, so this is a full count while the agent is on
(as long as the collector's trace buffer does not overflow).

## Impact

- Full-text search misses those pages entirely, not just the word with the bad character.
- Nothing visible: the job finishes successfully and the page is counted as indexed.
- Affects every library that indexes OCR with stray control characters: OCR from old conversions, mis-decoded encodings
  (the indexer has a separate repair option for that, `OCR_REPAIR_MISDECODED_UTF8_KEY`), or damaged files.

## Fix

Smallest fix (XS): in `normalizeWhitespacesForOcrText`, also remove characters that XML 1.0 does not allow, e.g.
`.replaceAll("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\uFFFE\\uFFFF]", " ")` before collapsing whitespace. Then the fallback is no longer
reached for OCR. Keep the fallback, but log it at SEVERE and count it in the job summary.

Better fix (S, part of [PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md)): build the `SolrInputDocument` directly
and drop the XML round trip.

## Test

- Unit test: `normalizeWhitespacesForOcrText("a\u0006b")` returns `"a b"`.
- Indexer test with an OCR fixture containing U+0006: the resulting Solr document has `text_ocr` with the surrounding words, and
  no "Reindexing without text_ocr" message is logged.

## Missing upstream

Not reported (closed kramerius#738 is a related K5 symptom, not this path). An issue for `ceskaexpedice/kramerius` should
state:

- **Finding:** `normalizeWhitespacesForOcrText` (`Indexer.java:390–400`) removes only characters matched by `\s`. Other
  control characters (U+0000–U+0008, U+000E–U+001F) remain, dom4j writes them as `&#6;`, and
  `SolrIndexAccess.indexFromXmlString` fails with `DocumentException` when it parses the XML back. The indexer then
  indexes the page again with empty OCR (`Indexer.java:307–319`), so the whole page drops out of full-text search and
  only a log line remains.
- **Fix:** replace characters not allowed in XML 1.0 with a space in `normalizeWhitespacesForOcrText`; longer term, build
  the `SolrInputDocument` directly, without the XML round trip ([PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md)).

## Related

- [PM-004](../perf-medium/PM-004-batch-solr-writes-in-indexer.md): removing the XML round trip fixes this and batches the writes.
