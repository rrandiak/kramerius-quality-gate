---
id: PH-002
former_id: IDEA-011
category: perf-hard
title: Store FOXML and OCR in zstd-compressed groups per parent (issue, volume, monograph), with a short-lived cache of unpacked groups; compress ALTO per file
area: storage
impact: high             # one NFS read per issue instead of two per page in indexing; ~80% less storage
effort: XL               # new storage format, PID-to-group lookup, migration; per-file compression alone is M
touches: [akubra (low-level storage, read and write paths), kramerius (group hint on reads), kramerius-helm-chart (config)]
contracts: [storage-format, config]
data_migration: true     # existing FOXML and OCR must be regrouped; can run in the background with mixed reads
use_cases: [indexing, image-open, storage, ingest]
review: [07-storage-options]
---

# PH-002 — Store FOXML and OCR in zstd-compressed groups per parent (issue, volume, monograph), with a short-lived cache of unpacked groups; compress ALTO per file

> **In one sentence:** packing the FOXML and the OCR of all children of one parent (an issue, a volume, a monograph) into
> one zstd file each makes a group read on MZK's NFS cost about what one file read costs today, so indexing needs one read
> per issue instead of two per page, readers paging through an issue are served from a short-lived cache, and groups stay
> small even for periodicals with hundreds of thousands of pages; ALTO stays one file per page, compressed.

## Today

Akubra keeps two filesystem blob stores on NFS, one for object XML (FOXML) and one for managed datastreams, each with an
MD5-based `##/##/##` directory layout (`AkubraDOManager.java:119–127`, akubra `51d821b`; [run 07](../raw/07-storage-options.md)).
A managed (`M`) datastream such as ALTO or TEXT_OCR is written as its own file: on save, `convertManagedStream` moves its bytes
to the datastream store under `pid+DSID+version` and leaves an `INTERNAL_ID` reference in the FOXML
(`AkubraDOManager.java:342–360`). So an ordinary page is three files: FOXML, ALTO and TEXT_OCR. Nothing is compressed, and
every read opens one file by PID through `ILowlevelStorage`. Writes go to `<id>/new` and are then renamed over the old file
(`AkubraLowlevelStorage.java:329`, `:396`).

Indexing reads each page's FOXML about four times and its OCR once or twice (`Indexer.readOcrText`; the next page's OCR
again when a page ends with a hyphen, [PM-001](../perf-medium/PM-001-read-once-then-prefetch.md)). In production an
Akubra read takes 1–7 ms (`AkubraRepositoryImpl.get` p50 1.3 ms, `getDatastreamContent` p50 5–7 ms, indexing traces of
2026-10-27).

## What was measured

**Sample:** 52 MZK titles, 7,410 objects (monographs and periodicals up to periodical / volume / issue / page), exported
on 2026-10-27 and rebuilt into the storage layout (export inlines managed streams; the rebuild puts them back as separate
files).

**Size** (zstd-3 unless noted):

| Stored file | Size | per file | per file + dictionary | grouped per **own parent** | grouped per title root |
| --- | --- | --- | --- | --- | --- |
| FOXML | 61 MB (p50 7.8 KB) | 4.4× | 18.6× | **38.8×** | 39× |
| TEXT_OCR | 24 MB (p50 2.5 KB) | 1.8× | 2.0× | **2.4×** | 2.4× |
| ALTO | 464 MB (p50 47 KB) | **5.4×** | 5.6× | — | 5.8× |

Grouping by own parent compresses as well as grouping a whole title, and the groups stay small:

| Group per own parent | Members | Compressed size |
| --- | --- | --- |
| FOXML (131 groups) | p50 38, p90 155, max 739 | p50 6.7 KB, p90 27 KB, max 140 KB |
| TEXT_OCR (98 groups) | p50 44, p90 192, max 738 | p50 96 KB, p90 182 KB, max 1.2 MB |

ALTO is 85% of all bytes, compresses well on its own, and is read one page at a time, so it stays per file. With FOXML and
OCR grouped and ALTO per file, the sample shrinks from 549 MB to about 98 MB, about −82%.

**At MZK's scale** (object counts per model path from the search index, 2026-10-28; sizes scaled from the sample's per-object
averages, so they are estimates):

| | Count | Average children |
| --- | --- | --- |
| all objects | 78.1 M | |
| pages and tracks | 76.9 M (98.4%) | |
| parents (everything else) | 1.23 M | |
| monographs | 266,510 | 209 pages |
| periodical issues | 689,242 | 22.5 pages |
| monograph units | 12,444 | 353 pages |

| Stored today | Size | Files | With this idea |
| --- | --- | --- | --- |
| FOXML | ~0.64 TB | 78.1 M | ~17 GB in ~1.2 M groups |
| TEXT_OCR | ~0.26 TB | ~76.9 M | ~108 GB in ~1.2 M groups |
| ALTO | ~5.0 TB | ~76.9 M | ~0.94 TB, still one file per page |
| **Total** | **~5.9 TB** | **~232 M** | **~1.06 TB, ~79 M files** |

An average monograph's FOXML group would be about 44 KB and its OCR group about 300 KB compressed; an issue's, a few KB and
about 30 KB.

Periodicals are why groups must follow the own parent, not the title: the 4,888 MZK periodicals hold 16.9 M objects, with a
median of 532, p99 of 52,236 and a maximum of 356,947 objects per periodical. 17 periodicals have more than 100,000 objects
(18% of all periodical objects). A group per title root for the largest would be about 75 MB of compressed FOXML and about
500 MB of OCR.

**Read time on NFS** (MZK, 2026-10-28; the sample written to a scratch export on the Akubra NFS server from one
cluster node and read from another node with a cold page cache; groups per title root, the larger case):

| Read | Per file today | Grouped |
| --- | --- | --- |
| one random page | 2.73 ms | 3.57 ms for its whole group (p50 15 KB) |
| every page of every title | 3.82 ms per object | about one group read per group |

Own-parent groups are smaller than the title groups measured (6.7 KB against 15 KB at p50), so a group read should cost about
one file read. The scratch export (`/vol_dk_kube/…`) is on the same server as the Akubra stores (`/vol_fedora_clone_kube/…`)
but not necessarily on the same disk.

**The largest direct parents** (MZK, 2026-10-28; the three parents with the most direct pages by `count_page`, files
read read-only from the Akubra NFS stores, zstd-3):

| Parent | Children | FOXML per file → group | TEXT_OCR per file → group | ALTO per file → group | All files, per file → groups |
| --- | --- | --- | --- | --- | --- |
| periodical item | 3,068 | 4.2× → 50.8× (25.0 MB → 0.5 MB) | 2.2× → 6.2× (10.9 MB → 1.8 MB) | 7.2× → 13.4× | 6.4× → 13.6× |
| monograph | 3,128 | 4.2× → 44.0× (24.3 MB → 0.6 MB) | 2.1× → 3.2× (15.5 MB → 4.8 MB) | 5.3× → 6.0× | 4.8× → 6.2× |
| monograph | 2,975 | 4.1× → 44.6× (23.1 MB → 0.5 MB) | 2.0× → 3.0× (13.7 MB → 4.6 MB) | 5.3× → 5.8× | 4.8× → 6.0× |

With the proposed layout (FOXML and TEXT_OCR grouped, ALTO per file), these parents shrink from 365 / 304 / 287 MB raw to
48 / 55 / 53 MB (5.5–7.6×), and from ~9,000 files each to ~3,000 ALTO files plus ~25 chunks. ALTO is ~90% of what remains.

FOXML groups of ~3,000 members compress like the sample's small groups, and chunks of 1,000 members lose nothing (50.4×
against 50.8×). Grouping ALTO adds 10% on monographs and about 2× on the periodical item; it stays per file because it is
read one page at a time and dominates the bytes. One group with every file of the parent is no smaller than one group per
kind, so FOXML and each datastream kind can live in separate files at no cost. A whole 3,000-page parent's FOXML is ~25 MB
unpacked, so a single-page read from an unchunked group would decompress ~25 MB; chunks keep that bounded.

Chunks of N members in page order, each an independent zstd frame, same three parents (compressed chunk size; time to
decompress one chunk, which is what a single-member read costs on a cache miss):

| Kind | Chunk | Ratio (3 parents) | Chunk p50 | Unpack one chunk p50 |
| --- | --- | --- | --- | --- |
| FOXML | 100 | 43.1–47.0× | 17–18 KB | 0.10 ms |
| FOXML | **250** | **44.0–49.6×** | **41–44 KB** | **0.25 ms** |
| FOXML | 1,000 | 44.0–50.4× | 162–176 KB | 1.4–1.5 ms |
| TEXT_OCR | 100 | 2.8–5.6× | 59–159 KB | 0.2–0.5 ms |
| TEXT_OCR | 250 | 2.9–5.8× | 141–386 KB | 0.5–1.3 ms |
| TEXT_OCR | 1,000 | 3.0–6.1× | 0.55–1.5 MB | 2.3–5.8 ms |
| ALTO | 100 | 5.8–13.3× | 0.8–1.4 MB | 5–8 ms |
| ALTO | 1,000 | 5.8–13.4× | 7.6–14 MB | 54–85 ms |

For FOXML, 250 members keep the ratio within 2% of a whole-parent group, and one chunk is about one of today's file reads
on NFS plus 0.25 ms to unpack. TEXT_OCR gains 1.4–2.8× from grouping, and 100–250 members keep almost all of it, but its
chunks are up to ten times larger than FOXML's (up to ~400 KB at 250 members); a byte cap (e.g. 256 KB compressed) next to
the member cap keeps OCR chunks near 100–150 members on dense books. For ALTO, even 100-member chunks cost 5–8 ms to unpack for every single page, against a
per-file ratio of 5.3–7.2×; ALTO stays per file.

**How readers move through titles** (gateway logs, 6 h, image `info.json` opens; referers carry only the site, so "same
title" is inferred from timing):

| Client | Opens | Pages per client per 30 min | Next new page within 60 s |
| --- | --- | --- | --- |
| browsers, direct | ~9,000 | p50 1, p90 16; 94% of opens come in a window with other pages | 84% (58% within 10 s) |
| CDK forwarding (4 clients) | ~28,000 | p50 172 | — |
| bots and tools | ~3,900 | 72% open one page | — |

## Idea

1. **Per-file zstd for ALTO now** (M). A compressing decorator around `ILowlevelStorage` compresses on write and recognises
   zstd frames on read by their magic number (`28 B5 2F FD`); anything else is returned as is, so old files stay readable and
   no migration is needed. The same decorator can compress OCR and FOXML per file until step 2 exists.
2. **Grouped per own parent, configurable per datastream** (XL). Every object lives in the group of its own parent, at
   every level: pages in their issue's or monograph's group, issues in their volume's, volumes in their periodical's. Only
   roots (titles, collections) keep a file of their own, or share one group for roots. Per parent there is one group file
   for FOXML and one per grouped datastream kind. Which kinds are grouped is a setting, for example:

   | Datastream | Storage |
   | --- | --- |
   | FOXML, TEXT_OCR, small XML streams (MODS, DC, RELS-EXT inline) | grouped per parent, zstd |
   | ALTO | one file per page, zstd |
   | images, PDF, audio (already compressed) | one file each, as they are |

   A group is split into chunks in page order, each closed at a member cap or a compressed-size cap, whichever comes first
   (defaults 250 members and 256 KB, settings; see the chunk measurement above), each chunk an independent zstd frame, so reading one page decompresses one chunk, not the whole parent.
   A periodical with hundreds of thousands of pages becomes thousands of small groups; a new issue creates new groups and
   touches only its volume's group.
3. **A write** reads the group, replaces one member, writes `<group>/new` and renames it, like Akubra does for single files
   today, under a lock per group instead of per PID.
4. **A cache of unpacked groups on each pod**, bounded by bytes and kept a few minutes. A miss costs about one file read; a hit
   costs none. With the locality above, most browser and CDK reads after the first page of an issue would be hits.
5. **Indexing reads one FOXML group and one OCR group per parent**, which also removes the repeated reads of
   [PM-001](../perf-medium/PM-001-read-once-then-prefetch.md) step A and the second read of the next page's OCR.

The hard part is not speed but **finding the group of a PID**: Akubra reads by PID, and a UUID says nothing about its parent.
Decided design:

- **Group files are the source of truth and describe themselves.** Each chunk carries a member table (PID, datastream,
  offset, length, checksum). Everything else can be rebuilt from the group files by reading the ~1.2 M groups once.
- **The PID → group index lives in Postgres** (`pid → group, chunk`; ~78 M rows, a few GB, ~1 ms per lookup). It is updated
  in the same step as the group's write and rename, and can be rebuilt from the groups if it is ever lost or wrong. A
  database is the safe shared index for many pods; an index file on NFS (SQLite and similar) is not safe with several
  writers.
- **Callers pass the own parent as a hint** where they know it: public read paths already load the PID path from Solr for
  the rights check, and indexing walks down from the parent. The table is used only without a hint.

Rejected:

| Lookup | Why not |
| --- | --- |
| a stub file per PID pointing to its group | keeps the 78 M files and adds a second NFS read (~2.7 ms) per lookup; the groups already make the index rebuildable, so stubs add no safety |
| hash of the PID → one of N fixed files | the hash ignores the parent, so a whole issue is no longer one read; unrelated writers rewrite the same files; changing N moves everything |
| the processing index (Solr) | ~36 ms per lookup |

Other rules: objects with foster parents are grouped by their own parent only; an object moved to another parent moves
between groups (group write plus index update).

## Expected gain

| Use case | Today | After (rough) | Confidence | Basis |
| --- | --- | --- | --- | --- |
| indexing reads for a 40-page issue | ~40 FOXML reads (×~4) + ~40 OCR reads, ~3–4 ms each cold | 2 group reads | medium | NFS benchmark, sample groups |
| indexing a periodical of 100,000 pages | ~200,000+ file reads | a few thousand group reads | medium | scales with groups, not pages |
| image opening, first page of an issue | 2.7 ms FOXML read | about one file read (cache miss) | medium | NFS benchmark |
| image opening, later pages of the same issue | 2.7 ms each | memory (cache hit) | medium | locality: 84% of browsers' next pages within 60 s |
| storage for FOXML + ALTO + OCR at MZK | ~5.9 TB | ~1.06 TB | medium | sample ratios × MZK object counts |
| files on NFS at MZK | ~232 M | ~79 M (ALTO per page, plus ~2.5 M groups) | high | object counts |

The read gain overlaps with [PM-001](../perf-medium/PM-001-read-once-then-prefetch.md) step A (read once per object)
and with FOXML caching in [PH-001](PH-001-cache-by-invalidation-need.md). Groups per parent also make
processes that rewrite all pages of an issue or volume cheap.

## Pros

- Reads scale with the number of parents, not pages: one read per issue for indexing, CDK harvesting and paging readers.
- Groups stay small (KB to about 1 MB) whatever the size of the title, so single-page reads and writes stay cheap.
- About 80% less storage and backup volume (mostly from per-file ALTO compression, which can ship first and alone).
- Writes stay atomic per file (write to `new`, rename), as today.

## Cons and risks

- **Write amplification and contention:** changing one page rewrites its parent's group (6.7 KB p50, 140 KB max in the
  sample), and two writers on pages of the same parent wait for each other.
- **Blast radius:** a damaged chunk loses up to one chunk of FOXML or OCR, not one page. Per-member checksums, a verification
  tool and backups matter more; the Postgres index also needs backups (MZK's CNPG clusters have none today), although it
  can be rebuilt from the groups.
- **Lookup and moves:** the PID → group rule must be maintained on ingest, delete, reparenting and chunk splits.
- **Migration** of the whole repository, with mixed old and new layouts during it.
- **Tools that read FOXML or OCR files directly** from NFS (scripts, other libraries' utilities) stop working without Akubra.
- **The cache** must be invalidated on write across pods, or be short-lived enough that a stale read is acceptable
  ([PH-001](PH-001-cache-by-invalidation-need.md) tier B).

## Alternatives

1. **Do nothing.**
2. **Per-file zstd only** (step 1 for all three, FOXML with a dictionary at 18.6×): the space saving without the read gain and
   without a storage-format change. A safe first step either way.
3. **Group per title root**: same compression, but unbounded groups; the largest MZK periodical (356,947 objects) would need
   a ~75 MB FOXML group and a ~500 MB OCR group, read for any page and rewritten for every new issue. Rejected.
4. **Filesystem compression on the NFS server** (ZFS or Btrfs with zstd): space saving with no code change; no read gain.
5. **Only read once and prefetch in Kramerius** ([PM-001](../perf-medium/PM-001-read-once-then-prefetch.md)): reduces
   repeated reads but still opens one or two files per page.

## Effort

**Size: XL** for grouping, set by the storage format, the lookup and the migration (see [effort scale](../README.md#effort)).

| Part | Size | Why this size |
| --- | --- | --- |
| Per-file zstd decorator (step 1) | M | new component in Akubra, config, mixed old and new files |
| FOXML dictionary (alternative 2) | S | training, versioning, shipping with config |
| Grouped store per parent with member index, cap and chunks, per-group lock | L | Akubra storage format |
| PID → group lookup (hint plus table) | L | Akubra API, Kramerius callers, DB table |
| Cache of unpacked groups | M | new component, invalidation rule |
| Migration of existing FOXML and OCR into groups | XL | whole repository, coordination with other libraries using Akubra |

## How we would validate it

1. Repeat the NFS benchmark with groups per own parent, on the Akubra export itself (a scratch directory under
   `/vol_fedora_clone_kube`), with a sample that includes the largest MZK periodicals; add a write benchmark (replace one
   member of a group versus one file).
2. Prototype the grouped store behind the same `ILowlevelStorage` interface and run one indexing job of a large periodical
   and an image-open replay against it in staging; compare per-page time, NFS operations, and public p95.
3. Measure the cache hit rate on a replay of a day of gateway logs before building the cache.
4. Drop grouping if staging shows write contention on busy parents, or if PM-001 step A alone removes most of the read cost.

## Open questions

- Does any process still write to the object store's files directly, outside Akubra? The production store is
  `objectStore-hardLink` on `/vol_fedora_clone_kube`, which suggests a hard-link clone of an earlier Fedora store.
- The sizes above are scaled from a 52-title sample; the real byte count of the MZK stores would confirm them.
- Which other libraries use Akubra's storage directly, and would they adopt a grouped format?
