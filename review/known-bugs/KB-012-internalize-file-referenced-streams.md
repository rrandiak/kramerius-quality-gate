---
id: KB-012
former_id: IDEA-013
category: known-bug
title: Copy file-referenced managed datastreams into Akubra on ingest, as Fedora did, and repair the objects that still point to import folders
area: storage
impact: medium           # removes a silent dependency on import folders; affected share of the repository unknown
effort: S                # internalize on ingest and resolve on export; the repair job is M
touches: [akubra (ingest, export), kramerius import processes]
contracts: [storage-format]
data_migration: true     # existing references must be copied in by a repair job
use_cases: [ingest, image-open, search, storage]
review: [07-storage-options]
checked: [source, production, upstream-report]
checked_how: "Read Akubra convertManagedStream at 51d821b and import at Kramerius 560676c; 55 file-referenced objects in one MZK export; kramerius#1138"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-012 — Copy file-referenced managed datastreams into Akubra on ingest, as Fedora did, and repair the objects that still point to import folders

> **In one sentence:** Fedora copied a managed datastream's referenced file into its own store on ingest and Akubra does
> not, so objects imported that way still read their OCR and ALTO from the import folder; adding that copy step to Akubra's
> ingest, and repairing existing objects once, makes the repository self-contained again.

The Kramerius developers consider this missing Fedora functionality rather than a defect, so it is an idea, not a bug.

## Today

Akubra `51d821b` and Kramerius `origin/master` `560676c`:

- **Where the references come from.** The METS convertor writes ALTO and TEXT_OCR as files in its export folder and references
  them with `file:` URLs when `convert.txt` is `referenced` or `external` (`createOCRStream`, `createAltoStream`,
  `processes/import-mets/.../convertor/BaseConvertor.java:1059`, `:1834`); the default is `encoded`
  (`import-mets/src/main/resources/res/configuration.properties:71`). Objects that came over from Kramerius 5 carry the same
  references; Fedora resolved them on ingest.
- **Akubra keeps the reference.** On save, `convertManagedStream` moves only inline `binaryContent` into the datastream store
  and rewrites it to an `INTERNAL_ID` reference (`AkubraDOManager.java:342–360`); a `contentLocation` of `TYPE="URL"` stays.
- **Reads follow the URL live.** `RepositoryUtils.getDatastreamContent` reads `TYPE="URL"` references with `readFromURL` at
  request time (`RepositoryUtils.java:135–145`), so the page works only while the file exists at that path on every pod.
- **Export cannot include them**, even when the file exists: a separate defect,
  [BUG-016](../bugs/BUG-016-export-fails-on-file-referenced-streams.md).
- **Upstream knows the symptom.** [kramerius#1138](https://github.com/ceskaexpedice/kramerius/issues/1138) reports indexing
  failing after an import's files were removed; [KB-006](KB-006-import-leaves-file-referenced-managed-streams.md)
  confirms the cause on current master. This idea is the fix and the repair for that issue.

**Seen at MZK (2026-10-27/28):** in an export of 52 titles (7,410 objects), 55 objects of one title, from 8 import batches,
have ALTO and TEXT_OCR as `file:/kramerius_ndk/import/<batch>/…` references. 7 days of logs show 110 such export errors in
curator and 73 `FileNotFoundException` for `/kramerius_ndk/import/…` paths in one public pod while those files were being moved.
The share of the 78 M objects affected is not known.

## Idea

1. **Internalize on ingest.** In `convertManagedStream`, also handle `TYPE="URL"` with a `file:` reference: read the file,
   store it in the datastream store under `pid+DSID+version`, and rewrite the reference to `INTERNAL_ID`. Fail the ingest if
   the file cannot be read. Leave `http(s)` references (image servers, `E` and `R` streams) as they are. A configuration
   switch can keep today's behavior for installations that rely on it.
2. **Repair job for existing objects:** find `M` streams with `file:` references, copy in the files that still exist, and
   list the objects whose files are already gone so they can be re-imported. The import process being written at MZK can be
   this job.

## Expected gain

| Use case | Today | After | Confidence | Basis |
| --- | --- | --- | --- | --- |
| OCR and ALTO of affected pages after an import folder is cleaned | lost | kept | high | source |
| backups of the object and datastream stores | miss these streams | complete | high | source |
| pods that must mount import folders | all | none, for reading | high | source |

## Pros

- The repository becomes self-contained again, as it was with Fedora.
- Small change in one place on ingest; the repair job can run in the background.

## Cons and risks

- Ingest becomes slower for such imports (one file copy per stream) and needs read access to the import folder at ingest time.
- An installation that deliberately keeps large streams outside the repository needs the switch.

## Alternatives

1. **Do nothing**, and keep every import folder forever on paths every pod mounts.
2. **Only the repair job**, run after each referenced import. Works, but every import process has to remember it.
3. **Import with `convert.txt=encoded`** only. Prevents new cases; does not fix K5-migrated objects.

## Effort

**Size: S** for Akubra; the repair job is M. The export fix is [BUG-016](../bugs/BUG-016-export-fails-on-file-referenced-streams.md) (see [effort scale](../README.md#effort)).

| Part | Size | Why this size |
| --- | --- | --- |
| Internalize `file:` references in `convertManagedStream` | S | one method, one config switch |
| Repair job over existing objects | M | scan of FOXML, copy, report |

## How we would validate it

1. Ingest an object whose ALTO is `CONTROL_GROUP="M"` with `<contentLocation TYPE="URL" REF="file:/tmp/x.xml"/>`, delete
   `/tmp/x.xml`, and read the ALTO; it must still be there.
2. Run the repair scan on a copy of the object store and compare the count of `file:` references before and after.

## Open questions

- How many objects at MZK still have `file:` references? A scan of FOXML for `CONTROL_GROUP="M"` with `TYPE="URL"` would tell.
- Do other libraries import with `convert.txt=referenced`, or still hold K5-migrated objects with such references?
