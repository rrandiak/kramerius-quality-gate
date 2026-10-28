---
id: KB-008
former_id: BUG-041
category: known-bug
title: PDF generation fails when ALTO specifies uppercase ROTATION
area: pdf
severity: medium
effort: XS
use_cases: [image-open]
review_ref: [H12]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1333
checked: [source, production, upstream-report]
checked_how: "Read PdfTextUnderImage at Kramerius 560676c; 3 MZK PDF 500 traces 2026-10-28; kramerius#1333"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-008 — PDF generation fails when ALTO specifies uppercase ROTATION

> **In one sentence:** a valid ALTO rotation attribute makes PDF selection return 500 because the renderer reads the attribute with the wrong case.

## Symptom

Three PDF selection HTTP 500 traces in a rolling production window had `NumberFormatException` as a root cause and `cz.knav.pdf.PdfTextUnderImage.getRotation` as the first Kramerius application frame. This is separate from the PDF font `ConcurrentModificationException` already recorded as BUG-015.

## Cause

Kramerius `origin/master` at `560676c85d276bd53f2dbaae95e87ddc6abd6e07`, `PdfTextUnderImage.java:240–250`: `getRotation` searches the current ALTO element and its ancestors for uppercase `ROTATION`, then calls `e.getAttribute("rotation")` with a lowercase name. DOM attribute names are case sensitive, so the latter returns an empty string even when `ROTATION` is present. `Float.parseFloat("")` throws `NumberFormatException`, which prevents the PDF from being generated. The text-placement call reaches this helper at `PdfTextUnderImage.java:120@560676c`.

## Evidence and frequency

On 2026-10-28, a read-only ClickHouse OTel aggregate over PDF selection server spans in the preceding six-to-one-hour window returned three HTTP 500 traces whose stack traces contained `Caused by: java.lang.NumberFormatException`. A class-and-method-only extraction over a twelve-to-one-hour rolling window returned `cz.knav.pdf.PdfTextUnderImage.getRotation` for all three. No search terms, PIDs, URLs, or stack traces left the cluster. These are observed traces, not a fixed-window request rate.

## Impact

PDF selection fails for pages whose ALTO text elements have `ROTATION` on the element or an ancestor. The same PDF renderer is used through public and CDK selection routes; the aggregate did not attribute these three failures to one route individually.

## Fix

Read the attribute using the already defined `rotation` constant: `e.getAttribute(rotation)`. Keep the existing zero-degree default when no ancestor has `ROTATION`.

## Test

Use an in-memory DOM fixture with a text element beneath an ancestor carrying a valid uppercase `ROTATION` value. Assert that the renderer uses that angle without throwing, then check that a tree without `ROTATION` keeps the zero-degree default.

## Related

- [H12 in the independent review](../raw/26-bug-hunt-2.md#candidates).
- [BUG-015](../bugs/BUG-015-pdf-font-scan-per-request.md) covers the separate concurrent font-registry failure on PDF generation.
- [Kramerius issue #1333](https://github.com/ceskaexpedice/kramerius/issues/1333) reports this same defect upstream.
