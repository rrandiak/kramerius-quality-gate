---
id: BUG-015
former_id: BUG-015
category: bug
title: Every PDF request rescans all font directories into iText's global font registry, and concurrent PDFs fail with ConcurrentModificationException
area: pdf
severity: medium
effort: XS               # bind GeneratePDFServiceImpl as a singleton, or register fonts once at startup
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read the PDF service at Kramerius 560676c; 7 days of MZK public Tomcat logs (831 CME lines)"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-015 — Every PDF request rescans all font directories into iText's global font registry, and concurrent PDFs fail with ConcurrentModificationException

> **In one sentence:** the PDF service registers every font directory with iText's process-wide `FontFactory` in its
> constructor, and because it is not a singleton a new instance is built for every PDF request, so each request repeats the
> scan while other requests read the same registry, and PDFs generated at the same time fail with
> `ConcurrentModificationException`.

## Symptom

Users downloading a PDF selection from the client API get an error. In the Tomcat log of a public pod:

```
SEVERE … java.util.ConcurrentModificationException
    at … (iText FontFactory internals)
    at cz.knav.pdf.PdfTextUnderImage.putTextsToPdf(PdfTextUnderImage.java:115)
    at cz.knav.pdf.PdfTextUnderImage.imageWithAlto(PdfTextUnderImage.java:83)
    at cz.incad.kramerius.pdf.commands.Image.process(Image.java:100)
    …
    at cz.incad.kramerius.pdf.impl.SimplePDFServiceImpl.pdf(SimplePDFServiceImpl.java:97)
    at cz.incad.kramerius.rest.apiNew.client.v70.pdf.AbstractPDFResource.selection(AbstractPDFResource.java:138)
    at cz.incad.kramerius.rest.apiNew.client.v70.pdf.PDFResource.selection(PDFResource.java:295)
```

## Cause

Kramerius `origin/master` `560676c`:

- `PdfTextUnderImage.registerFontDirectories` calls `FontFactory.registerDirectories()` (all system font directories)
  and `FontFactory.registerDirectory(...)` for the configured one (`shared/common/.../cz/knav/pdf/PdfTextUnderImage.java:54–64`).
  `FontFactory` is iText 2.1.7's static, process-wide registry (`com.lowagie:itext:2.1.7`). The method's own Javadoc says not
  to call it in a servlet. It sets `registerFontDirectoriesDone = true` (line 63), but nothing ever reads that flag.
- `GeneratePDFServiceImpl` calls it from its constructor (`GeneratePDFServiceImpl.java:89–95`).
- `GeneratePDFServiceImpl` is bound without a scope (`PDFModule.java:32`) and has no `@Singleton`, and it is injected into
  `AbstractPDFResource` (`AbstractPDFResource.java:89–90`). Jersey resources bound without a scope (`ApiServletModule.java:155–157`)
  are created per request, so each PDF request builds a new `GeneratePDFServiceImpl` and rescans the fonts.
- While one request is scanning (writing into `FontFactory`'s maps and lists), another request's `putTextsToPdf` calls
  `FontFactory.getFont` (`PdfTextUnderImage.java:115`), which iterates the same structures. That throws
  `ConcurrentModificationException`.

## Evidence and frequency

Seen in production at MZK: in 7 days of Tomcat logs to 2026-10-28, both public pods logged 831
`java.util.ConcurrentModificationException` lines. On `kramerius-public-0` the most frequent Kramerius frames in those stack
traces are all on this path, `PdfTextUnderImage.putTextsToPdf:115` down to `PDFResource.selection:295` (906 occurrences each;
one failure can be logged more than once, by `ExtAuthFilter` and by Tomcat). Only the top frames were extracted, so a
second, rarer CME source is not ruled out.

Each scan also logs `registred fonts <n>` at INFO, so its frequency can be counted directly:

```sh
grep -c 'registred fonts' /usr/local/tomcat/logs/catalina.<date>.log
```

## Impact

- Failed PDF downloads whenever two PDF requests overlap (selections of pages with ALTO).
- Every PDF request pays for a full scan of the system font directories before rendering, CPU and file reads on the public pod.
- The registry keeps being rewritten, which can also leave a request using a font set that is half registered.

## Fix

1. Bind `GeneratePDFService` as a singleton (`bind(...).to(GeneratePDFServiceImpl.class).in(Scopes.SINGLETON)` in
   `PDFModule.java:32`), as the neighbouring `FirstPagePDFService` bindings already are.
2. Make `registerFontDirectories` run once: check `registerFontDirectoriesDone` under a lock (or move the call to application
   startup, e.g. `StartupServlet`), and make the flag `volatile`.

Either step alone stops the per-request rescan; both together also protect other callers of `registerFontDirectories`.

## Test

- Unit test: create two `GeneratePDFServiceImpl` instances; `FontFactory.registerDirectory` must be called once.
- Staging: 20 concurrent PDF selection requests on pages with ALTO; no `ConcurrentModificationException`, one `registred fonts`
  log line per pod start.

## Related

- The same per-request construction pattern may hold for other unscoped services injected into Jersey resources; a scan of
  `bind(...)` calls without a scope that do work in their constructors would find them.
