---
id: KB-006
former_id: BUG-046
category: known-bug
title: FOXML import leaves file-referenced managed OCR and ALTO outside Akubra
area: ingest
severity: high
effort: S
use_cases: [ingest, indexing, storage]
review_ref: [GH5]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1138
checked: [source, upstream-report]
checked_how: "Read Import at Kramerius 560676c and AkubraDOManager at Akubra 51d821b; incident in kramerius#1138; MZK imports not counted"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-006 — FOXML import leaves file-referenced managed OCR and ALTO outside Akubra

> **In one sentence:** importing FOXML with managed streams referenced by files can succeed while later indexing cannot read those streams once the import files are gone.

**GitHub issue verification:** this report checks [upstream issue #1138](https://github.com/ceskaexpedice/kramerius/issues/1138) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream issue reports a successful FOXML import followed by indexing failures for OCR or ALTO files referenced outside Akubra.

## Cause

Kramerius `Import.java:618–639@560676c85d276bd53f2dbaae95e87ddc6abd6e07` unmarshals FOXML and calls `akubraRepository.ingest` without internalizing file-referenced managed streams. Akubra `CoreRepositoryImpl.java:103–112@51d821bcb55b89050e834ea00651aeb051146495` passes the object to `AkubraDOManager.write`. That method invokes `convertManagedStream`, but `AkubraDOManager.java:342–359@51d821bcb55b89050e834ea00651aeb051146495` copies only `binaryContent`; a managed version containing only `contentLocation` remains an external reference in the stored FOXML. This is distinct from BUG-016, which concerns export of such references after storage.

## Evidence and frequency

Source-confirmed for file-referenced managed streams at the pinned revisions. [Upstream issue #1138](https://github.com/ceskaexpedice/kramerius/issues/1138) reports a subsequent file-not-found indexing failure; this review did not inspect the affected package or count MZK imports.

## Impact

The repository can report a completed import while text layers remain dependent on temporary or external files. After those files are removed, search indexing and later reads lose OCR and ALTO content.

## Fix

On ingest, copy managed file-referenced content into Akubra and replace the reference only after the copy succeeds. Reject the import if required content cannot be copied. Provide a repair pass for existing affected objects, as outlined in KB-012.

## Test

Use a local temporary file and an in-memory FOXML fixture containing a managed OCR reference. After ingest, remove the test file and assert that the stored stream remains readable from Akubra.

## Related

- [GH5 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).
- [KB-012](KB-012-internalize-file-referenced-streams.md) describes the broader internalization and repair plan.
- [BUG-016](../bugs/BUG-016-export-fails-on-file-referenced-streams.md) covers export of still-referenced streams.
