# Kramerius Quality Gate — scratch plan

Working notes, not a spec. `PLAN.md` is the pitch; this file is how we get there.

## 1. What we found (inputs)

**Kramerius 7** (`ceskaexpedice/kramerius`, local clone at tag `v7.2.2.3`)
- Java 21, Tomcat 9, Gradle + Jib images: `ceskaexpedice/kramerius`, `curator-worker`, `public-worker`, `process-manager`.
- Dependencies:
  - Solr cores: `search`, `processing` (relations; written on every ingest), `logs`, `monitor`.
  - PostgreSQL (users, rights, licenses, folders, stats) plus a separate process-platform DB.
  - Akubra FS storage: `objectStore` holds FOXML, `datastreamStore` holds managed streams, in `##/##` MD5-hashed dirs.
  - Also Hazelcast locks, IIPImage, Keycloak, memcached.
- Storage seam: everything goes through `AkubraRepository`, but `AkubraDOManager` **hardcodes `FSBlobStore` + `HashPathIdMapper`**. Filesystem assumptions also leak out (`getObjectStorePath()` returns a `File`, `exists()` checks disk, rebuild processes read `objectStore.path` directly). A new backend means code changes in akubra and in `AkubraRepositoryProvider`. It is not a config switch.
- Hot user paths: `client/v7.0/search`, `items/{pid}/image/thumb`, IIIF/zoomify tiles (proxied to IIP with a rights check), `info/structure`, `metadata/mods`, `ocr/text|alto`, `pdf`.
- Observability: **no OTel, Micrometer or Prometheus in the code.** The only metric is `SolrAPICallMonitor`, which writes to the Solr `monitor` core above 1 s.
- Config comes only from `~/.kramerius4/configuration.properties`. **Environment variables are not mapped to config keys**, so the harness must template the properties file.
- Ingest: POST `/admin/v7.0/processes` with profile `import` (FOXML) or `convert_and_import` (NDK METS), then `new_indexer_index_object`.
- Sample data: only the "Drobnůstky" monograph (17 FOXML files, about 1.5 MB). Too small to benchmark with.

**Helm chart** (`rrandiak/kramerius-helm-chart` v1.4.0, appVersion 7.2.0)
- Image tags are plain values, which gives us the version knob for free.
- Storage volumes are `type: nfs | pvc`, which gives us the storage knob. NFS `mountOptions` covers v3/v4 and sync/async.
- `observability.enabled` deploys Vector, ClickHouse and HyperDX, injects the OTel javaagent from a PVC, and runs otel-collector with a **spanMetrics connector that sees 100% of spans**. This is most of our telemetry pipeline already.
- **Not included:** Solr, Keycloak, a dev cluster setup, data seeding. Postgres can run in-chart (`databases.mode: pg`).

**kdsm** (`moravianlibrary/kdsm`, design-only, **not under git**)
- Latency is shaped by Toxiproxy on k3d in front of NFSv3 (ports 111/2049/20048), MinIO and Mongo. Knobs: `SLOW_MS` and `RATE_KB`.
- Key finding: whole-document read cost is driven by **round-trip count**. pidHash placement needs 67 GETs and takes 463 ms; anchor placement needs 3 GETs and takes 24 ms. At +40 ms added latency that becomes 1.47 s vs 52 ms. Current Akubra (one file per object, one file per datastream) is on the bad side of this.
- Pitfalls to turn into harness rules:
  - Stale toxics invalidated a whole campaign.
  - `ms // 2` rounds 1 ms down to 0.
  - Output dirs that aren't cleared inflate results through appends.
  - NFS sync vs async changes results by about 10x and must be recorded.
  - netem shapes egress only.
  - Every campaign needs an unshaped control run.
- `notes/benchmarks.md` already has good methodology to lift: fidelity profiles, site probe profiles (`sites/mzk.yaml`), and "pin two axes, sweep one" campaigns.

**Other useful repos**
- `kramerius-client` (Python, Keycloak auth): can seed data, run processes and harvest PID lists.
- `kramerius-metrics-sidecar`: exposes process failure counts, usable as a small gate signal.

## 2. Shape of the system

```
campaign.yaml ─► orchestrator (Python) ─► env provisioner (k3d + helm + toxiproxy)
                     │                          │
                     │                          ▼
                     ├──► seeder ─────────► Kramerius + Solr + PG + Akubra(NFS via toxiproxy)
                     │                          │  OTel javaagent
                     ├──► load gen (k6) ───────►│  (traceparent per request)
                     │                          ▼
                     │                     otel-collector ─► ClickHouse
                     ▼                                          │
                evaluator ◄─────────────────────────────────────┘
                     │   (baseline vs candidate, span breakdown)
                     ▼
                report (md/html) + pass/fail exit code
```

Proposed tech choices (not final):
- **Orchestrator and evaluator:** Python (uv, Ruff), one CLI `qg`. It reuses `kramerius-client`, and kdsm is already Python.
- **Load generator:** k6. It has scripted scenarios, open and closed arrival models, and cheap high concurrency, and it can set `traceparent` itself. Locust is the fallback if we want everything in Python.
- **Environment:** k3d, following kdsm (context `k3d-mzk`). It is local, reproducible and cheap to rebuild. Later the same campaigns can target a real staging cluster.
- **Telemetry:** the chart's observability stack, with sampling forced to 100% in bench mode.

### Correlating benchmark runs and traces
- Each run is deployed with `OTEL_RESOURCE_ATTRIBUTES=qg.run_id=…,qg.variant=…`, so every span is tagged with its run.
- k6 generates the `traceparent` for every request and logs `(trace_id, scenario_id, iteration, vu)` to a side table in ClickHouse. The join goes `run → scenario → iteration → trace`, with no dependency on baggage propagation.

### Bottleneck attribution: an important gap
The OTel javaagent auto-instruments HTTP (Solr, IIP, Keycloak), JDBC and Hazelcast. It does **not** instrument Akubra file I/O. We have to add method spans through `otel.instrumentation.methods.include`; the chart already has `includeMethods`. Targets: `FSBlobStore`/`AkubraDOManager` read and write, `AkubraRepository.get*`, and datastream getters. Without these, "storage %" just ends up inside "Kramerius self-time". Time breakdown per scenario = span self-time grouped by `{kramerius, solr, postgres, storage, iip, other}`.

## 3. Test matrix axes

| Axis | Values (first) | Values (later) |
|---|---|---|
| Kramerius version | 7.2.2 (baseline) vs 7.2.3 / branch build | any tag, PR images |
| Storage medium | local-path PVC, NFS (ganesha / kernel nfsd) | S3/MinIO, kdsm packed store |
| Storage shaping (Toxiproxy) | none, `lan` (1 ms), `wan` (20–40 ms), `rate`-limited | `sites/mzk.yaml` probe replay, fault injection (timeouts, resets) |
| NFS options | v3 sync (default) | v4, async, rsize/wsize |
| Load | 1 VU (latency), step ramp to saturation | soak (1 h), spike |
| Search backend | Solr 9.6 | Elasticsearch/OpenSearch (compat contract) |
| DB | PG 16 | PG version drift |

Campaign rule (from kdsm): pin all axes but one, always include a control run, and repeat each cell N≥5 times.

## 4. Scenarios (first 12)

Read path, anonymous:
1. `search` with a simple query plus facets
2. `search` with a heavy query: fulltext, highlighting, deep paging
3. `items/{pid}/info/structure` on a large periodical
4. `metadata/mods` + `dc`
5. `image/thumb` for a random page (cold and warm)
6. IIIF `info.json` plus a tile sweep over one page, to simulate a viewer
7. `ocr/text` + `ocr/alto`
8. "Browse a book": a realistic mixed session (structure → thumbs → N pages of tiles and OCR)
9. `pdf` / `asyncpdf` for a 50-page range

Write path, admin:

10. FOXML `import` of a batch (throughput as objects/s)
11. `new_indexer_index_object` reindex of a batch
12. `processing_rebuild` (a pure storage walk, so it shows storage sensitivity best)

Each scenario gets:
- a fixed PID set or query set, drawn from the dataset manifest with a seed
- a workload model: closed with N VUs, or open at an arrival rate
- correctness assertions: status code, response hash or schema, expected hit counts

## 5. Dataset: a synthetic corpus generator (`qg gen`)

We don't export production data. We look at the *shape* of production data (aggregate statistics only) and generate our own "lorem ipsum" corpus with the same shape, on demand.

### Principles
- **Deterministic.** The same `(spec, seed, size)` always gives byte-identical output. PIDs are `uuid5(ns, spec-digest/seed/node-path)`, so there are no random UUIDs and two specs never share pids. All draws go through `random.Random.random()` only, whose stream CPython guarantees, so output also survives Python and library upgrades.
- **Prefix-stable scaling.** The corpus is a stream of *units*: a monograph, or the next **issue** of a periodical title (one open title and volume per profile). Each root draws from its own keyed stream, and the generator emits units until the page budget is met, so a 100k-page corpus *contains* the 10k-page corpus. Only the volumes and titles still open at the budget differ, because their FOXML lists fewer children; `corpus.json` names them as `truncated`. Benchmarks at 10k and 100k with the same spec should look alike in shape, and any difference then comes from scale, not from different data.
- **Page-share quota, not random draws, picks the mix.** Each next unit goes to the model and profile furthest below its target *share of pages* (`mix.py`). Drawing by title count left a 10k corpus with no periodicals: they are 1.8% of roots but 21% of pages. A single daily volume (~2–4k pages) was also still too coarse a unit, which is why periodicals are scheduled by issue.
- **1–3 knobs per distribution.** All knobs live in a YAML *spec* (`specs/mzk-like.yaml`, `specs/tiny.yaml`, …): the model mix, the profiles per model, and their knobs. Size is a separate CLI argument, never part of the spec.
- **Cheap vs faithful payloads.** Every heavy payload (images, PDF) has a `mode: pool | render`:
  - `pool`: reuse K pre-made files, which is fast.
  - `render`: generate from the ALTO, which is realistic but slow.

### What the FOXML looks like
Checked against the sample in `kramerius/installation/0eaa6730….zip`:
- **Root and inner nodes** (e.g. monograph) hold `BIBLIO_MODS`, `DC` and `RELS-EXT` as inline X datastreams, plus `POLICY` as E and `AUDIT`.
  - `RELS-EXT` carries `hasModel`, `itemID`, own-child relations (`hasPage`, and presumably `hasVolume`/`hasItem`/`hasUnit`, still to verify). It also carries `policy`, which we don't generate: access is licenses only.
- **Page** holds `IMG_FULL` (M; djvu/jp2/jpeg), `IMG_THUMB` and `IMG_PREVIEW` (M, jpeg), `TEXT_OCR` (M), `ALTO` (M; not in this sample but standard), their `*_ADM` streams, and `BIBLIO_MODS`/`DC`/`RELS-EXT`.
- Managed streams are base64-inlined in the FOXML, which makes a page about 150 KB.
- **To verify in K7 code:** relation names for collections (foster relations like `contains`/`isOnPage`), and the license/`containsLicense` fields.

### Structure model: profiles

The data (`calibration/findings.md`) shows that structure is a **mixture of archetypes**, not one smooth distribution per level. So the generator is built from *profiles*:

```
root model ──(model mix)──► profile ──(profile mix)──► title-level params ──► unit-level draws
 e.g. periodical             daily                      this title's median     each issue's pages
                                                        pages/issue
```

- **Model mix:** `page_share` per root model, e.g. monograph 0.79 and periodical 0.21 of pages. Title counts per profile are emergent and serve as a validation target.
- **Profile mix per model:** `page_share` over that model's profiles.
- **A profile** is a small bundle of distributions, each with 1–3 knobs. A shared pattern covers most of them, a **two-level lognormal on a lattice**:
  - `title_median ~ LogNormal(median, σ_between)`
  - `unit ~ LogNormal(title_median, σ_within)`
  - snap the unit to multiples of 4 with probability `p4`, else to multiples of 2 with probability `p2`, else leave it odd.

  That is 3 knobs for the envelope plus 2 for the lattice.
- **Emergent totals are validation, not knobs.** Pages per periodical (lognormal μ 6.31, σ 1.85), pages per volume, and page share per profile must come out right without being set directly. `qg gen --validate` compares a generated corpus with `data/derived/*` targets.

**Periodical profiles.** The first cut is the frequency class, fitted in `calibration/findings.md`:
- annual, 2–3 per year, quarterly, bimonthly, monthly, biweekly, weekly, several per week, daily.
- Each has these draws:
  - volumes per title: lognormal, profile-independent except for daily
  - issues per volume: the nominal frequency × a dispersion, plus `p_incomplete_volume`
  - pages per issue: the two-level lattice lognormal
  - supplements per volume and per issue: Poisson, plus their own pages
  - articles per issue: Poisson; articles own pages in journal-like profiles
- Merging adjacent classes (e.g. biweekly+weekly, several per week+daily) is fine if the fit holds. The goal is the fewest profiles that reproduce the validation targets.

**Other models.** First-cut profiles, taken from the child-count mixtures:

| Model | Profiles |
|---|---|
| graphic | single sheet (92%), album (tail lognormal) |
| map | sheet (87%), sheet+verso (7%), atlas (tail) |
| sheetmusic | score (odd-biased lattice, median 25 pages), nested sheetmusic / monographunit |
| soundrecording | 2 soundunits × {single track (52%), album side 5–7}, with 2 label pages |
| convolute | 2 + geometric members of {monograph, sheetmusic, graphic} |
| manuscript | plain (median 454 pages, no lattice), with internalparts |
| archive | bimodal: short (2 pages), long (median ~120) |
| monograph | single-part (98%, lognormal median 178 pages, σ 0.9, mod-4 lattice, small leaflet mode), multipart (2%: units 2 + geometric, units median 292 pages) |
| collection | a forest (113 top-level collections, depth ≤ 4, rare 2nd parent), members lognormal (median 20, σ 1.7), per-model membership share (graphic 94% … monograph 7%) |

**Non-structural draws** are still a first cut, not yet measured:
- page size and dpi: categorical
- text density: `p_blank`, lines, words per line
- illustrations
- metadata pools (titles, authors, publishers): Zipf
- dates: consecutive volume years
- born-digital PDF share
- licenses: a categorical over license *sets* per model (e.g. monograph `dnnto+onsite` 58%, graphic `public` 98%). For periodicals it is drawn per volume. No public/private policy.
- ALTO flavour: always present, with a named producer drawn from the real producer mix (MISSING/UNKNOWN excluded), plus the schema version mix (v2/v3/v4)

Why Zipf matters: plain lorem ipsum has about 70 distinct words. That produces a tiny Solr fulltext index with degenerate posting lists, so search benchmarks would be meaningless. A Zipf vocabulary gives realistic term statistics.

### What a generated object must look like (from `calibration/findings.md`, FOXML shapes)
- Images are **external by default**: IMG_* is `E` pointing to an IIP-style tiles URL, and inline `M` on ~10% only. So **ALTO is the main Akubra payload** (median 49 KB). The FOXML/datastream store benchmark gets realistic automatically, and the image path goes through the image server.
- Parents list every child in RELS-EXT (`hasPage`/`hasItem`/…), so parent RELS-EXT grows linearly with child count.
- RELS-EXT vocabulary per model (own: `hasVolume`, `hasItem`, `hasPage`, `hasUnit`, `hasIntCompPart`, `hasSoundUnit`, `containsTrack`; foster: `isOnPage`, collection `contains`, legacy `isMemberOfCollection`).
- `license` goes on the level where it is set (monograph root, periodical **volume**), and `containsLicense` on the ancestors.
- **Virtual pages:** born-digital PDF documents get search-only pages `<uuid>_<n>`. They are indexed but have no FOXML, and the generator emits them only into the index path.
- **Canonical by default; data errors are opt-in.** The default specs produce only valid Kramerius data. Production mistakes live in a separate `noise` block, used only by an explicit `specs/mzk-legacy.yaml` in robustness scenarios (does version X still tolerate legacy data?), never in performance gates.
  - **Mistakes (noise block only):**
    - the `licence` typo
    - wrong MIME types (ALTO as `text/plain`/`octet-stream`, RELS-EXT as `text/xml`)
    - unparsable ALTO
    - orphan roots
    - `normalPage` casing
    - odd edges (volume→volume, periodical→monographunit, volume→monograph)
    - licenses on pages
    - legacy `policy`/`POLICY` and `isMemberOfCollection vc:`
    - pages without ALTO, and ALTO without a producer
  - **Legitimate variation (in canonical specs):**
    - ALTO v2/v3/v4
    - volumes owning pages directly (1.6% of volumes, some mixed with issues)
    - virtual pages
    - multiple licenses, and `containsLicense`
    - supplements on volumes, articles owning pages
    - ALTO without `WC`
  - **A separate benchmark axis, not variation:** images `E` (image server) vs `M` (inline in Akubra).
  - **ALTO rule:** every generated page has ALTO, and every ALTO names its producer (drawn from the producer mix of the real data, without the MISSING/UNKNOWN share).

### Payload pipelines
There are separate generators with separate inputs. They share only the seed and the document tree.
- **Content (page level):** ALTO comes from the text model (blocks → lines → words, with bboxes and page dims). **`TEXT_OCR` is derived from the ALTO**, and images can optionally be rendered from it (below).
- **Descriptive metadata:** `BIBLIO_MODS` is its own generator: a per-model template (titleInfo, name, originInfo, physicalDescription, identifiers, part/partNumber for volumes and issues, page type and number for pages), filled from the metadata pools and the tree position. `DC` is a separate generator. Its shape follows real K7 data, where DC mirrors parts of the MODS but not by a fixed transform, so we model it independently from real samples.
- **Structural and technical:** `RELS-EXT` is built from the tree only: model, own-child relations, foster relations to collections, licenses, `tiles-url`, and file. The `*_ADM` streams come from the technical properties of the payload.

Images:
- `render`: draw the ALTO words at their bboxes onto a paper-coloured canvas (Pillow), encode JPEG/JP2 at the target pixel dims, and derive thumbnail and preview from that.
- `pool`: pick from K pre-rendered images per size class, chosen by hash.

PDF for born-digital documents: render pages to PDF from the same ALTO (reportlab), or take one from the pool.

### Emitters
- **`foxml`:** a directory tree for the `import` process. This is the realistic path, and it is also scenario 10.
- **`akubra`:** write straight into the `##/##` hashed objectStore/datastreamStore layout, then run `processing_rebuild` + reindex. This is much faster for 100k+ pages and lets us snapshot a seeded state quickly.
- **`manifest.json`:** every PID with its model, parent, page count and payload sizes. Workloads sample PIDs from it (with a seed), and assertions check against it (for example, the expected hit count for a query term).

### Calibration: "how production looks"
There are two sources. Neither ends up in the corpus.

**1. Structure statistics: the public search API** (`https://api.kramerius.mzk.cz/search/api/client/v7.0/search`, anonymous, Solr-style `q`/`fq`/`facet`)
- Useful fields: `model`, `own_parent.pid`, `own_parent.model`, `root.model`, `own_model_path`, `level`, `page.type`, `page.index`, `licenses.facet`, `licenses_of_ancestors`, `ds.img_full.mime`, `has_tiles`, `date_range_start.year`, `languages.facet`, `authors.facet`.
- **Means:** `numFound` counts per `(model, own_parent.model)` give them directly.
- **Distribution shape:** seeded random sampling of parents (a random `start` offset over a stable sort), then one `rows=0` count query per sampled parent. That fits lognormal/NegBin parameters from about 500 samples per level. We rate-limit ourselves politely.
- **Tails:** `facet.field=own_parent.pid` with `facet.limit=N` returns the top-N largest parents.

First probe on MZK (2026-09-25), about 77.9M Solr docs:

| Relation | Count | Mean |
|---|---|---|
| pages / monograph | 55.6M / 266k | **≈ 209** (tail: 6441) |
| pages / monographunit | 4.39M / 12.4k | ≈ 353 |
| pages / periodicalitem | 15.4M / 689k | **≈ 22** |
| items / periodicalvolume | 688k / 45.4k | **≈ 15** |
| volumes / periodical | 45.4k / 4.87k | ≈ 9.3 |
| pages / map | 47.7k / 15.9k | ≈ 3 |
| pages / sheetmusic | 371k / 7.25k | ≈ 51 |

Other findings from the probe:
- The model mix also includes `article` 81k, `supplement` 80k, `graphic` 20k, `collection` 819, `convolute` 267, `internalpart` 1.3k, and `soundrecording`/`soundunit`/`track`. The generator must support at least `supplement` and `article`.
- **Access is modelled by licenses only** (`licenses.facet`, `licenses_of_ancestors`), never by the public/private `policy`. The license mix matters for per-request rights-check cost; its distribution is still to be measured.
- **`page.type` mix:** NormalPage 96%, then TitlePage, TableOfContents, Index, covers, Blank, and so on. It even has a `normalPage` casing variant, which is realistic noise we may want.
- **IMG_FULL mime:** 99.9% `image/jpeg`, with jp2 negligible.

**2. Datastream shapes: full FOXML samples**
- Source: the admin archive export, `GET /search/api/admin/v7.0/repository/export?format=archive&pid=…` (Bearer token). This is what `akubra_export_archive` uses, and it is also in `kramerius-client` as `akubra.export(pid, FoxmlExportFormat.Archive)` and in kdsm `examples/fetch_documents.py`. It returns the whole object with every datastream inlined (managed content base64-encoded).
- Pull a small, seeded, stratified sample (per model, a few dozen objects) to learn:
  - the real MODS/DC/RELS-EXT templates and which elements vary;
  - ALTO structure (density, block and line layout, attributes);
  - image pixel dims and byte sizes per `page.type`;
  - `*_ADM` contents, and FOXML and datastream size distributions.
- **These samples are for reference only.** They stay local, outside git and outside any generated corpus. What we keep are the fitted parameters and the element templates (structure, never values).

`qg calibrate --site mzk` runs both steps and writes `specs/mzk-like.yaml`, which holds only numbers and templates.

### Storage of generated data
Nothing generated goes into git. The cache key is `(spec hash, seed, size, generator version)`. We also snapshot the seeded PVCs and the Solr index per key so runs don't re-seed.

## 6. Gates and evaluation

- **Baseline:** a stored result set for (version, env-profile, dataset-version).
- **Metrics per scenario:** p50/p95/p99, throughput at SLO, error rate, span-time share per component, backend call counts per request (Solr queries, SQL statements, file reads, which catches N+1 regressions), and JVM/pod CPU and memory.
- **Statistics:** repeated runs, a bootstrap CI on the p95 delta, and a fail only when the CI excludes the threshold. This avoids flaky gates. Call counts are deterministic, so they get exact gates.
- Rules live in `gates.yaml` per scenario, e.g. `p95_delta <= +10%`, `solr_calls_per_req == baseline`, `errors == 0`.
- **Output:** a markdown or HTML report in the one-paragraph style from `PLAN.md`, plus a CI exit code.

### Run environment fingerprint
Gates run wherever the user runs them: a laptop, a bench node or CI. Absolute numbers therefore only mean something within one environment. A small Linux script, `scripts/envinfo.sh`, dumps `env.json` into every result. It records:
- **Host:** kernel, distro, CPU model, core count, frequency governor, SMT, memory, swap, transparent hugepages (THP), and load average at start.
- **Disks:** device and type (NVMe/SSD/HDD from `lsblk -o ROTA`), filesystem, and mount options for every volume in use.
- **Container stack:** docker, k3d, k8s and helm versions, image **digests** (not tags), and a hash of the rendered values and `configuration.properties`.
- **Shaping:** NFS server type and export/mount options, and the active Toxiproxy toxics (read back, not what we asked for).
- **Versions:** the git SHA of this repo and the generator version.

The evaluator compares fingerprints. If the baseline and the candidate come from different environments, it warns (or refuses, if `--strict`), and it shows which fields differ.

## 7. Phases

**P0 — Skeleton (1–2 wk)**
- `git init`, conventions (Makefile, Ruff, uv), and a `qg` CLI stub.
- k3d cluster, the helm chart (minimal profile, `pg` mode), plus Solr 9.6 and Keycloak with realm import.
- Seed Drobnůstky and hit one endpoint by hand.

**P0.5 — Generator v0 (1–2 wk, in parallel with P0)**
- Spec schema (model mix → profiles), the monograph + periodical + page tree, the ALTO/OCR/MODS/DC/RELS-EXT builders, pool images, and the `foxml` emitter with its manifest.
- A determinism test (same seed gives the same bytes) and a prefix-stability test (10k ⊂ 100k).
- Import the output with `import` and confirm that Kramerius renders it.
- Later: maps and graphics, collections, rendered images, PDFs, the `akubra` emitter, and `qg calibrate`.

**P0.5 status (2026-09-25):** `qg gen` works for monographs (single, leaflet, multipart) and periodicals (9 frequency profiles, supplements, articles, volumes owning pages). It is deterministic and prefix-stable (tested), mixes by page share, runs at ~5 ms/page, and produces ALTO close to production size (median 40 KB vs 49 KB, ~140 vs ~160 B/word). Monograph structure matches production at 10k and at 100k. Open items:
- **Per-profile validation (`qg gen --validate`):** compare many generated titles per profile with the fitted tables (issues per volume, pages per issue, supplements). Corpus-level issue statistics can't do this at 10k–100k, because such corpora hold only a few titles per profile (a 100k corpus has ~1–2 daily titles). Corpus-level issue pages are currently median 4 vs production 8.
- **Disk:** a full 100k corpus is ~15 GB and doesn't fit in `/tmp` (tmpfs, 7.5 GB) or in the free space on `/home`. Large corpora need a dedicated volume, or the `akubra` emitter with compression.
- Not built yet: the other root models, collections, virtual pages / PDF, inline (`M`) images, the `akubra` emitter, the noise layer (`mzk-legacy`), and `qg calibrate`.

**P1 — First measurement (2 wk)**
- OTel javaagent in, 100% sampling, ClickHouse receiving spans, Akubra method spans added.
- k6 running scenarios 1, 3, 5 and 8 with traceparent injection.
- A first span-breakdown query and a first run on local-path storage.

**P2 — Storage axis (2 wk)**
- Port kdsm's Toxiproxy NFS manifests, including its validation fixes (recreate proxies per profile, echo the active toxic, fail on 0 ms).
- Campaigns local vs NFS vs NFS+lan/wan, then write up the first bottleneck findings.

**P3 — Version axis and gates (2 wk)**
- Baseline store, evaluator, `gates.yaml`, and the report.
- Compare 7.2.2 vs 7.2.3 and wire it into CI (manual dispatch first).

**P4 — Load**
- The remaining scenarios, and saturation and soak profiles, at 10k vs 100k pages to check that shape holds across scale.

**P5 — New ideas**
- Storage prototype behind the Akubra seam, targeting S3/MinIO first and the kdsm packed store second. This needs a small upstream refactor so `AkubraRepositoryProvider` can pick a `CoreRepository` impl.
- A Solr → OpenSearch compatibility contract, where the scenario assertions become the contract.

## 8. Open questions

- ~~Where are gates run?~~ Wherever the user runs them, with an env fingerprint (§6).
- ~~Production data?~~ No export. We use a synthetic generator calibrated on aggregate statistics (§5).
- ~~Calibration source?~~ MZK public search API for structure, admin archive export for datastream shape (§5).
- **Admin token** for the archive export: whose token, which instance, and is a sample of a few hundred objects OK?
- **Generator speed budget:** how long can generating 100k pages take? This decides the default between `pool` and `render`.
- **IIP in scope for v0?** Do image tiles count as a user hot path now, or later?
- **Upstream appetite:** will ceskaexpedice accept the Akubra `BlobStore` seam refactor, and possibly native OTel?
- **kdsm:** it is not under git, so version it before we copy from it.
- **How this project relates to kdsm:** does kdsm become a candidate backend that the quality gate evaluates, or does the gate absorb kdsm's storage microbenchmarks? Proposal: keep microbenchmarks in kdsm and end-to-end benchmarks here.
