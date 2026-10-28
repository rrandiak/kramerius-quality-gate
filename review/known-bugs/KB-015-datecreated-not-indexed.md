---
id: KB-015
former_id: BUG-044
category: known-bug
title: Date indexing omits MODS dateCreated
area: indexing
severity: medium
effort: S
use_cases: [search, indexing]
review_ref: [GH3]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1348
checked: [source, upstream-report]
checked_how: "Read DateExtractor at Kramerius 560676c; kramerius#1348; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-015 — Date indexing omits MODS dateCreated

> **In one sentence:** objects with a creation year only in `mods:dateCreated` have no indexed year to search or sort by.

**GitHub issue verification:** this report checks [upstream issue #1348](https://github.com/ceskaexpedice/kramerius/issues/1348) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream report describes a MODS record with `dateCreated` whose year is absent from the search index.

## Cause

`DateExtractor.java:71–77,99–112@560676c85d276bd53f2dbaae95e87ddc6abd6e07` selects the first `originInfo` and extracts only `dateIssued` values from it. Its fallback checks a part date, but never `dateCreated`. `SolrInputBuilder.java:843–847@560676c85d276bd53f2dbaae95e87ddc6abd6e07` writes date fields only from the returned `DateInfo`, so a creation-only date is lost.

## Evidence and frequency

Source-confirmed at the pinned revision. [Upstream issue #1348](https://github.com/ceskaexpedice/kramerius/issues/1348) reports an affected record; this review did not measure prevalence at MZK.

## Impact

Year filters, date sorting, and date displays based on the indexed fields omit affected works, including manuscripts that use creation dates.

## Fix

Use `dateCreated` when `dateIssued` is absent, with an explicit precedence rule when both exist. Reindex affected objects.

## Test

Use in-memory MODS fixtures with creation-only, issued-only, and both dates. Assert the indexed date fields follow the chosen precedence.

## Related

- [GH3 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).
