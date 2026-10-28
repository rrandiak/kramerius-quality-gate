---
id: KB-017
former_id: null
category: known-bug
title: FOXML import parses the whole package into memory before importing, so a large package runs the worker out of heap
area: ingest
severity: medium
effort: S                # one class: keep only the inventory fields, close the walk stream
touches: [kramerius/processes/import]
contracts: []
data_migration: false
use_cases: [ingest]
review_ref: []
upstream: https://github.com/ceskaexpedice/kramerius/issues/1364
checked: [source, upstream-report]
checked_how: "Read ImportInventoryFactory at Kramerius 560676c; OOM on large imports reported in kramerius#1364; not counted at MZK"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-017 — FOXML import parses the whole package into memory before importing, so a large package runs the worker out of heap

> **In one sentence:** before it imports anything, the FOXML import walks the whole package, unmarshals every FOXML into
> a JAXB object and keeps all of them in one map, only to decide between full and partial indexing, so heap use grows with
> the package and a large one ends in OOM, as kramerius#1364 reports.

## Upstream issue

| | |
| --- | --- |
| Issue | [kramerius#1364](https://github.com/ceskaexpedice/kramerius/issues/1364), open, 2026-10-20 |
| What it reports | OOM when importing larger packages, caused by the pre-processing that decides between full and partial indexing |
| Match | exact symptom and the same stage |
| What we add | the exact code, why memory grows with the package, and the fix |

## Symptom

An import job of a large package fails with `OutOfMemoryError` in the worker before any object is imported.

## Cause

Kramerius `560676c`, `processes/import/.../importer/inventory/ImportInventoryFactory.java`:

- `loadDigitalObjects` (lines 167–190) walks the import tree (`Files.walk(startPath, 20)`, line 170), unmarshals every
  `.xml` file into a `DigitalObject` (line 175) and puts each one into `digitalObjectMap` (line 185). Every parsed object of
  the package is in memory at the same time.
- The inventory built from it (lines 158–162) needs only a few fields per object (PID, model, title, children, whether it
  exists). For a full import it also keeps a reference to the whole `DigitalObject` in each `ImportInventoryItem`
  (`setDigitalObject`, line 160), so the objects stay reachable after the scan.
- The `Files.walk` stream is never closed (line 170), so its directory handles stay open until garbage collection.

Peak heap therefore scales with the size of the whole package, not with one object.

## Evidence and frequency

Source at `560676c`, plus the upstream report. MZK imports were not counted: a 30-day process aggregate on 2026-10-28
had no import jobs ([bug hunt 2](../raw/26-bug-hunt-2.md)).

## Impact

Large packages cannot be imported on a worker with a normal heap; the job fails before importing anything, and the
workaround is splitting packages or raising the heap.

## Fix

Keep only the inventory fields (PID, model, title, children, exists) while scanning, and release each parsed object
before reading the next; for a full import, parse the object again when it is imported instead of keeping it. Close the
walk stream (try-with-resources). If order matters for scheduling, sort the small inventory records, not the objects.

## Test

A test JVM with a small fixed heap (e.g. 128 MB) and a generated package whose total FOXML size is several times the heap:
before the fix the inventory stage fails with `OutOfMemoryError`; after it, the inventory completes and holds one record per
object.

## Missing upstream

The issue names the stage but not the code. Missing there:

- **Cause:** `ImportInventoryFactory.loadDigitalObjects` (lines 167–190) keeps every unmarshalled `DigitalObject` of the
  package in one map; for full imports each `ImportInventoryItem` keeps it too (line 160). The `Files.walk` stream is not
  closed.
- **Fix:** keep only the inventory fields during the scan and parse each object again at import time; close the stream.

## Related

- [QOL-008](../quality-of-life/QOL-008-one-foxml-parsing-layer.md): a light FOXML model would make the inventory scan
  cheap without JAXB.
- [BUG-008](../bugs/BUG-008-import-schedule-failure-reports-success.md), [BUG-019](../bugs/BUG-019-import-list-skips-missing-directories.md),
  [BUG-024](../bugs/BUG-024-import-merge-ignores-relation-write-failure.md): other import defects.
