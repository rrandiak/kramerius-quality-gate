# Calibration findings

Observations about the shape of production data. They feed the generator knobs, but this file holds no knobs yet.

## Periodicals: MZK pid_paths, 2026-09-10

Source: `data/raw/periodical.paths.txt`, with 4,858 titles and 15.9M pages (one line per page). The script is `calibration/periodical_paths.py`, and the full output is in `data/derived/periodical_paths.json`.

**Caveat:** the dump has no models, so levels are inferred from depth (periodical / volume / item / sub-item). These findings get re-run once the model list for non-page pids is available.

### Tree shape
- **98.2% of pages** sit at `periodical/volume/item/page`.
  - 206k pages are one level deeper (item/sub-item/page, probably supplements).
  - 86k pages hang directly on a volume.
  - 4 pages hang directly on a periodical.
- By title: 4,605 titles are pure `P/V/I/page`, and 194 also have sub-items. 31 titles mix pages-on-volume with issues, and 14 are pages-on-volume only.
- Volumes: 44,440 have only children, 242 have only pages, and 499 are mixed.
- Items: 22.8k (3%) carry sub-items, almost always exactly 1 (93%). A sub-item has median 4 pages (p90 12).

### Volumes per periodical
- median **3**, mean 9.3, p90 26, p99 72, max 151
- **31% of titles have exactly 1 volume**, and the counts decay monotonically (1, 2, 3, 4… = 1519, 648, 399, 304…)
- Lognormal fits poorly (KS 0.17) because of the mass at 1. A discrete heavy-tailed shape (1 + geometric/Yule, or a discretised lognormal) looks more likely.
- It correlates with nothing else: ρ = 0.11 with items per volume and −0.08 with pages per item.

### Items per volume
This is a title property, not a volume property. The ICC of log(items/vol) by title is **0.96**, and the within-title spread is small (σ_log ≈ 0.34).
- **61% of volumes have exactly 1 item.** 68% of titles have a median of 1 item per volume. These are "yearbook-like" titles, where the issue is the whole volume.
- The rest shows frequency modes. The top values are 12, 13, 11 (monthly), 52 (weekly), 4, 6, 2, and 10. There is also a daily cluster: 43 titles with a median of 251–400 items per volume.
- Title medians:

  | 1 | 2–3 | 4–5 | 6–9 | 10–15 | 16–30 | 31–60 | 61–120 | 121–250 | 251–400 | >400 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | 3328 | 242 | 188 | 210 | 393 | 163 | 219 | 27 | 26 | 43 | 4 |

- This suggests a mixture: a frequency class drawn per title (yearbook / quarterly / monthly / weekly / daily…), then a count around the class with a small dispersion and missing issues. Very different from a single NegBin (KS 0.72).

### Pages per item
- median **8**, mean 21, p90 46, p99 224, max 3068
- **96.8% even, 74% divisible by 4.** Printed sheets fold in 4s. The top values are 4 (204k), 8 (128k), 6, 16, 12, 2, 10, 20, 24, 32.
- This is also mostly a title property (ICC 0.81, within-title σ_log ≈ 0.49).
- **Coupled to frequency:** ρ(items per volume, pages per item) = **−0.46** by title, so frequent periodicals have thin issues. Yearbook-like titles have thick "issues", which make up the tail.
- Lognormal KS 0.19. The real distribution is a lattice (multiples of 2 and 4) with a lognormal-ish envelope, so it is probably best generated as `4 × round(lognormal / 4)`, with a small odd/2-only share.

### Emergent totals: validation targets, not knobs
These come out as a by-product of the generator. It must reproduce them without having them set directly.
- **Pages per periodical:** lognormal fits **very well**, μ = 6.31, σ = 1.85 (KS 0.023). Median 509, p90 6.1k, max 307k.
- **Pages per volume:** lognormal fits well, μ = 4.98, σ = 1.37 (KS 0.042). Median 164.

## Periodical profiles: with models, 2026-09-25

Scripts: `calibration/periodical_tree.py` joins `periodical.paths.txt` with `periodical.models.txt` into a node table (5 of 825k nodes have no model). `calibration/periodical_profiles.py` then classes titles by their median issues per volume.

### Structure by model
- **Edges:**
  - volume→item 685k
  - volume→**supplement 55k**
  - item→supplement 24k
  - item→article 10.5k
  - volume→article 88
  - plus a handful of oddities (periodical→monographunit, volume→monograph, volume→volume)
- **Page owners:**
  - items: 15.3M pages
  - supplements: 437k
  - **articles: 54k pages** (articles *do* own pages here; they are not only foster links)
  - volumes: 85k
- There are 81k articles in total, but only ~10.5k appear in page paths. The rest own no pages (presumably `isOnPage` foster links), and their parents are unknown from this dump.

### Profiles: classes by median issues per volume

| Profile | Titles | Pages % | Volumes med / p90 | Issues per volume med [p10–p90] | Pages per issue (title median) | σ between titles | σ within title | Supplements per volume | Supplements per issue | Articles per issue |
|---|---|---|---|---|---|---|---|---|---|---|
| annual | 3326 | 23.7 | 3 / 22 | 1 [1–1] | 100 | 1.12 | 0.51 | 0.00 | 0.001 | 0.059 |
| 2–3 per year | 246 | 6.9 | 3 / 26 | 2 [1–4] | 100 | 1.19 | 0.92 | 0.12 | 0.002 | 0.350 |
| quarterly | 191 | 4.3 | 4 / 31 | 4 [2–6] | 50 | 0.93 | 0.64 | 0.33 | 0.012 | 0.026 |
| bimonthly | 205 | 6.9 | 3 / 32 | 6 [3–12] | 36 | 0.85 | 0.62 | 0.25 | 0.034 | 0.324 |
| monthly | 393 | 16.7 | 6 / 40 | 12 [7–13] | 32 | 0.83 | 0.50 | 0.41 | 0.035 | 0.017 |
| biweekly | 159 | 4.6 | 3 / 24 | 24 [13–28] | 16 | 0.75 | 0.36 | 0.79 | 0.028 | 0 |
| weekly | 219 | 14.5 | 4 / 31 | 51 [26–53] | 12 | 0.75 | 0.39 | 0.82 | 0.019 | 0 |
| several per week | 50 | 3.6 | 3 / 28 | 104 [51–298] | 6 | 0.58 | 0.46 | 11.6 | 0.010 | 0 |
| daily | 46 | 18.2 | **15** / 58 | 302 [154–602] | 6 | 0.56 | 0.44 | **40.6** | 0.050 | 0 |

The σ columns are the spread of log pages per issue: between title medians, and within a title around its median.

What the table says:
- **Title count and page mass are very different.** Annuals are 68% of titles but 24% of pages. Dailies are 1% of titles but 18% of pages. A profile mix must be weighted *by title*, and page share then comes out as a validation target.
- **Pages per issue is hierarchical.** A title median is drawn from the profile, a lognormal with σ_between 0.6–1.2. Each issue is then drawn around the title median, with σ_within 0.4–0.5 (0.9 for 2–3 per year, which is really a mixed bag). This covers most of the variance: the earlier ICC of 0.81 was the between-title part.
- **Page counts sit on a lattice in every profile:** 91–99% even, 70–83% divisible by 4.
- **Issues per volume ≈ nominal frequency.** p25–p75 is within ±10% of the title median for most profiles. The low tail (p5 ≈ 0.25–0.5×) is incomplete volumes, and the high tail (p95 1.3–2.9×) is double numbering or supplements counted as issues. The share of volumes exactly at the median falls from 97% (annual) to 12% (daily).
- **Volumes per title is roughly profile-independent:** median 3–6, p90 22–40, max ~150. Dailies are the exception, with median 15.
- **Supplements depend on the profile:** they hang **on the volume** (40 per volume in dailies, less than 1 elsewhere) and rarely on the issue. They have 4–8 pages, or 24 in annuals.
- **Articles as page containers** appear only in journal-like profiles (2–3 per year and bimonthly at ~0.33 per issue; annual 0.06).

## Other root models: `other.paths-and-models.txt`, 2026-09-25

Script: `calibration/other_roots.py`. The input is 934k nodes with their model paths. Monographs and periodicals are excluded.

**Structure signatures per root model:**
- graphic → page: 19.6k roots
- map → page: 15.9k
- sheetmusic → page: 7.0k
- soundrecording → soundunit → track (+ page): 676
- archive → page: 548
- manuscript → page (+ internalpart): 246
- convolute → {monograph | sheetmusic | graphic} → page: 267
- **collection with no own children: 819.** Membership is foster-only, so it needs a separate source.
- **Orphans** (a non-top model as root): periodicalitem 805, page 608, supplement 296, periodicalvolume 43, internalpart 19. This is a data-quality artifact; the generator ignores it by default.

**Child counts, which are natural mixtures and so natural profiles:**

| Edge | Distribution |
|---|---|
| graphic→page | **92% exactly 1**, then 2 (4%), tail to 970 (p99 72): profiles *single sheet* / *album* |
| map→page | **87% exactly 1**, 2 in 7% (sheet + verso), tail to 760 (p99 42): *sheet* / *sheet+verso* / *atlas* |
| sheetmusic→page | median 25, p90 109, max 2826. **79% odd** (mod 4: 45% ≡ 1, 34% ≡ 3), probably covers plus parts, so the lattice is *not* the sheet lattice |
| soundrecording→soundunit | 96% exactly 2 (disc sides / media) |
| soundunit→track | 52% 1 track, then a 5–7 cluster (album side) |
| soundrecording→page | 78% exactly 2 (label front and back) |
| archive→page | bimodal: many 2s, median 119, tail to 2630 |
| manuscript→page | median 454, broad (p10 98, p90 901), no lattice (17% even) |
| manuscript→internalpart | median 4, 1–39 |
| convolute→member | 64% exactly 2, geometric tail to 21 |
| convolute's monograph→page | median 128, 57% even |

## Monographs: Solr child counts, 2026-09-25

The source is `calibration/fetch_solr.py`: facets on `own_parent.pid`, sliced by pid prefix. All three totals match `numFound` exactly. Script: `calibration/monographs.py`.

**Monograph profiles:**
- 261,157 monographs (98.1%) are **single-part** (pages only).
- 4,912 (1.8%) are **multipart** (monographunits).
- Only 2 have both.
- Rare children: internalpart 177, periodicalvolume 31, monograph 4, plus internalpart 133 under units.

| Distribution | n | Median | p10 | p90 | p99 | Max | Lognormal μ / σ | Even | mod 4 |
|---|---|---|---|---|---|---|---|---|---|
| pages / single-part monograph | 261k | **178** | 48 | 410 | 789 | 6441 | 5.04 / 0.91 | 0.90 | 0.62 |
| units / multipart monograph | 4.9k | **2** | 1 | 4 | 10 | 55 | — | — | — |
| pages / monographunit | 12.4k | **292** | 84 | 704 | 1314 | 2696 | 5.58 / 0.82 | 0.90 | 0.64 |

- **A single lognormal fits the pages well** (σ ≈ 0.9), unlike periodical issues. There is a small **leaflet** mode: 8 pages is the 2nd most common value (4.4k), and 5–16 pages account for about 3%.
- **Book lattice:** 90% even, 62% mod 4. The top single values are 16k + 4 (68, 36, 100, 132, 164, 84, 116, 52, 148), which looks like 16-page signatures plus 4 cover pages. In aggregate, though, it is only a mild preference: ≡4 mod 8 is 33% vs ≡0 mod 8 28%. So a mod-4 lattice with p4 ≈ 0.6, p2 ≈ 0.3 and ~0.1 odd is enough.
- **Units per multipart monograph:** 2 in 55%, 3 in 16%, 1 in 15%, then a geometric tail. Units are thicker than single volumes (median 292 vs 178).

**Licenses (as indexed):**
- 8 values: `onsite`, `dnnto`, `public`, `dnntt`, `mzk_public-muo`, `mzk_public-contract`, `onsite-sheetmusic`, `orphan`.
- Almost every document at every level has `licenses.facet`, including 76.1M of 76.7M pages. So the index shows propagated licenses. Where a license is *set* in RELS-EXT is not visible from Solr; that needs the FOXML samples.
- Multi-license sets are common (e.g. `dnnto+onsite`).

**Direct collection members by model** (`in_collections.direct`):
- monograph 19.0k, graphic 18.4k, map 9.2k, sheetmusic 4.2k, periodical 1.4k
- **collection 706**, which is nesting
- monographunit 365, page 347, manuscript 172, convolute 120, and a few items, volumes and articles

Members are mostly roots, but not only.

## Licenses and collections: roots, 2026-09-25

The source is `roots.tsv`: all 317,471 `level:0` documents, with licenses, `in_collections.direct` and `in_collections`, plus `collections.tsv`. Script: `calibration/roots.py`.

### License set per root, by model

| Model | License set mix |
|---|---|
| monograph | `dnnto+onsite` 58.5%, `onsite` 28.2%, `public` 12.6%, `dnntt+onsite` 0.4% |
| periodical | `dnnto+onsite` 48%, `public` 13%, `dnntt+onsite` 11%, `onsite` 11%, `dnnto+onsite+public` 8%, `dnnto+dnntt+onsite` 5% (mixed titles: licenses vary by volume) |
| graphic | `public` 98.5%, `onsite` 1.5% |
| map | `public` 68.5%, `onsite` 31.5% |
| sheetmusic | `mzk_public-muo` 63%, `public` 34%, `onsite-sheetmusic` 2.5% |
| soundrecording | `onsite` 75%, `public` 25% |
| convolute | `public` 83.5%, `mzk_public-muo` 16% |
| archive | `public` 100% |
| collection | *none* 69%, `public` 28% (collection licenses look like the union of its members') |

**License semantics** (confirmed by the user):
- FOXML RELS-EXT carries a license **only on the document where it is set**.
- Everything else is derived: `licenses_of_ancestors`, `contains_licenses` (possibly also stored in FOXML, to be checked in the samples), and the propagated `licenses.facet`.
- Solr's own `licenses` field shows where licenses are set, so the level where licenses are set can be measured from Solr too.

So the license mix is a **categorical over license *sets*, per model** (per profile, for periodicals). For periodicals the set is the union over volumes, so the generator should draw licenses at the volume level for periodicals and at the root for everything else. This still needs checking in the FOXML samples, to see where RELS-EXT actually carries them.

### Collection membership (direct, roots only)

| Model | Share in ≥1 collection | Collections per member doc |
|---|---|---|
| graphic | **94%** | 1 in 74%, 2 in 22%, 3 in 5% |
| sheetmusic | 60% | ≈1 |
| map | 58% | ≈1 |
| periodical | 30% | 1 in 77%, 2 in 20% |
| monograph | **7%** | 1 in 86%, 2 in 12% |
| others | ~0 | |

- **Members per collection:** median 20, p90 182, p99 972, max 3151. Lognormal μ 3.11, σ 1.73 on the non-empty ones. 86 of 819 have no root members at all.
- **Nesting:** 86% of collections have a parent collection (1 parent in 85%, 2 in 1%).
  - Depth: 0 in 113 collections (top level), then 333 / 133 / 158 / 82 for depths 1–4.
  - 688 contain only documents, 80 only sub-collections, and 45 both.
  - Sub-collections per parent: p90 2, max 66.
- This fits a *tree* (a forest of 113 roots, max depth 4) with rare second parents. Membership is decided by model more than by popularity. A generator shape follows:
  1. Build the collection forest.
  2. Give each collection a size from the lognormal and a *model affinity*: most collections are dominated by one model.
  3. Assign documents by a per-model p_in and a count of collections per document.
  4. Also make a few non-root members (monographunit 365, page 347, …).

## FOXML shapes: 699 archive exports, 2026-09-25

The sample comes from `calibration/sample_pids.py --seed 1`, and the analysis from `calibration/foxml_shapes.py`, whose output is `data/derived/foxml_shapes.json` (structure and numbers only). 4 pids were **virtual pages** (`<uuid>_<n>`), which are search-index pages created from a PDF and have no FOXML; the export returns "not found".

### Where the bytes are (what Akubra actually stores)
- **Page images are mostly *not* in Akubra.**
  - `IMG_FULL`/`IMG_PREVIEW`/`IMG_THUMB` are `E` (external URL to `imageserver.mzk.cz`, IIP) on about 80% of pages, and `R` (redirect) on 7%.
  - They are **inline `M` on only ~10%.** Those average IMG_FULL 1.16 MB at ~1880×2620, PREVIEW 160 KB at ~730×1000, THUMB 3.4 KB at ~93×128.
  - jp2 appears in 2%.
- **ALTO is the dominant local payload.**
  - It is `M` on ~89% of pages: median 49 KB, p90 256 KB, max 1.2 MB.
  - `TEXT_OCR` is median 2 KB.
  - Page FOXML files: median 79 KB, p90 1.18 MB (the inline-image ones).
- **Parent RELS-EXT grows with the number of children** (one `hasPage`/`hasItem` per child). Median sizes: monograph 10 KB, monographunit 28 KB, manuscript 24 KB. Reading structure means reading these, which matters for `info/structure` benchmarks.
- **Sound:** `track` has an inline `MP3` (median 7.6 MB), with `WAV`/`OGG` on 70%. This is the heaviest object class by far.
- The other datastreams are small:
  - MODS 0.5–9 KB, DC 0.3–3 KB
  - AUDIT median 0.4–5 KB (up to 13 KB)
  - `*_ADM` 0.1–0.6 KB, `IMG_FULL_AMD` about 30 KB when present
  - manuscripts sometimes have `TEI_P5` (~110 KB)
- The history is mostly flattened: 1 version per datastream; RELS-EXT has up to 7 on pages.
- **MIME noise is real.** ALTO is `text/plain` 51%, `text/xml` 30%, `application/octet-stream` 8%. RELS-EXT is `text/xml` in 16%. The generator should reproduce this, because parsers in the stack see it.

### Datastream presence per page
DC, BIBLIO_MODS, RELS-EXT, IMG_FULL, IMG_THUMB 100% · IMG_PREVIEW 91% · TEXT_OCR 90% · ALTO 89% · AUDIT 76% · POLICY (legacy, E) 75% · IMG_FULL_ADM 67% · TEXT_OCR_ADM 65%.

Non-page objects carry DC + MODS + RELS-EXT (+ AUDIT, POLICY). **Collections have no DC**: only MODS, RELS-EXT, and a thumbnail in 41%.

### RELS-EXT vocabulary (structural relations)

| Parent | Own-child relations | Foster / other |
|---|---|---|
| periodical | `hasVolume` | `containsLicense` (100%) |
| periodicalvolume | `hasItem`, `hasIntCompPart` (15%) | `license` (96%) |
| periodicalitem | `hasPage`, `hasIntCompPart` | |
| monograph | `hasPage`, `hasUnit` (multipart) | `license` 87%, `containsLicense` 10% |
| monographunit | `hasPage` | `license` 95% |
| soundrecording → soundunit → track | `hasSoundUnit`, `containsTrack` | `license` on the recording |
| convolute | `hasUnit` | `license` / `containsLicense` |
| supplement / article / internalpart | `hasPage` (supplements), or none | **`isOnPage`** foster links to pages |
| collection | **`contains`** (members listed in the collection, median 17, max 275), `standalone` | |
| any | `isMemberOfCollection` (legacy `vc:` pids; 25–60% of objects) | |
| page | | `tiles-url` (90%), `file` (78%) |

Also on most objects: `itemID`, `handle`, `contract`, `hasDonator`, `policy` (legacy, ignored). There are **typos in production**: `licence` on 4–8% of volumes and sheetmusic.

### Licenses in FOXML
They confirm the rule: a `license` sits on the document where it is set.
- Monographs: at the root. Periodicals: **on the volume**.
- `containsLicense` **is stored in FOXML**: always on periodical roots, and on multipart monographs and convolutes.
- **Pages carry none** (2% outliers).

The generator writes `license` at the set-level and `containsLicense` on ancestors.

### MODS / DC templates
The element paths per model are in `foxml_shapes.json` (`mods_paths`, `dc_paths`), with their presence rates. Main points:
- **page:** a minimal `part/detail[@type]/number` (100%), `part/@type` (96%), `identifier` (95%), `typeOfResource` (82%). titleInfo is only on 9%.
- **periodicalitem / periodicalvolume:** `titleInfo/partNumber`, `originInfo/dateIssued`, `identifier`, `genre`. Volumes also have `part/date` (93%).
- **monograph:** a full catalog record: titleInfo, originInfo (place, publisher, dateIssued, issuance), language, physicalDescription (extent, form), location (physicalLocation, shelfLocator), recordInfo (six sub-elements, 91%), name/namePart (80%), notes.
- **DC (monograph):** identifier, title 100%; publisher, language, date, type, format, rights, description 82–94%; creator 76%; subject 67%.

### ALTO
- 272 ALTO files, 4 of which have parse errors (as in production).
- Schemas: ALTO **v2 88%**, v4 10%, v3 1%. Units: pixel 93%.
- Page size: median 1692×2429, p90 3448×4792.
- Content, median (p90): 4 (38) blocks, 47 (270) lines, 306 (1916) strings, 9 lines per block, 5.6 strings per line, mean word length 5.1.
- Illustrations: median 1. HYP present on some pages.
- Word confidence (`WC`) on only 24%.
- Producer mix matches `periodical.alto-software.txt`: ABBYY RS 4.0, FineReader Server 14, PERO, tuzkaocr, FineReader 8, plus ~7% with no producer.

## Still to measure
- Collection model affinity: how dominated each collection is by one model (needs members joined with their model: in `roots.tsv`).
- ALTO software mix (`periodical.alto-software.stats.txt`): ABBYY RS 4.0 70%, FineReader Server 14 14%, tuzkaocr 6%, **MISSING 7%**. This matters for ALTO flavour and for the share of pages without ALTO.
