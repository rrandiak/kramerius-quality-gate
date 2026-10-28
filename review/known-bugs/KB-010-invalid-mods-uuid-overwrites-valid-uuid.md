---
id: KB-010
former_id: BUG-045
category: known-bug
title: An invalid empty MODS UUID can replace a valid identifier during NDK import
area: ingest
severity: medium
effort: XS
use_cases: [ingest]
review_ref: [GH4]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1312
checked: [source, upstream-report]
checked_how: "Read BaseConvertor and MetsPeriodicalConvertor at Kramerius 560676c; kramerius#1312; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-010 — An invalid empty MODS UUID can replace a valid identifier during NDK import

> **In one sentence:** NDK import can use an empty UUID even when the MODS record also contains a valid UUID.

**GitHub issue verification:** this report checks [upstream issue #1312](https://github.com/ceskaexpedice/kramerius/issues/1312) against the pinned source; it is not an independent production discovery.

## Symptom

The upstream issue reports failed NDK import when MODS has a valid UUID and an additional empty UUID marked `invalid="yes"`.

## Cause

`BaseConvertor.java:889–902@560676c85d276bd53f2dbaae95e87ddc6abd6e07` iterates every `IdentifierDefinition` of type `uuid`, ignores its `invalid` attribute, and assigns each non-null value to the same variable. A later empty value therefore replaces a valid earlier UUID. The caller at `MetsPeriodicalConvertor.java:377–381@560676c85d276bd53f2dbaae95e87ddc6abd6e07` generates a UUID only for `null`, then builds a PID from the empty string.

## Evidence and frequency

Source-confirmed for the ordering above at the pinned revision. [Upstream issue #1312](https://github.com/ceskaexpedice/kramerius/issues/1312) reports an affected NDK package; this review did not inspect the package or measure MZK frequency.

## Impact

A conforming MODS record with an explicitly invalid extra identifier can fail conversion or produce an invalid PID, preventing import of the affected item.

## Fix

Ignore identifiers marked invalid and blank values; retain the first valid UUID rather than overwriting it with later entries. Keep the existing generated-UUID fallback only when no valid UUID is present.

## Test

Use an in-memory MODS fixture with a valid UUID followed by an empty invalid UUID. Assert that `getUUIDfromMods` returns the valid UUID, including with the identifiers in reverse order.

## Related

- [GH4 in the GitHub issue cross-check](../raw/27-github-issues-crosscheck.md#verified-unmatched-bug-reports).
