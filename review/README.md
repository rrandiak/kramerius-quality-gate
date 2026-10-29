# Review

The results of the Kramerius review, one entry per file, meant to be shown to people outside the review: bugs in
Kramerius and its components (Akubra, process-platform, the CDK), bugs already reported upstream, web client bugs, and
performance and quality-of-life proposals. Each entry is built from the evidence in [`raw/`](raw/) and links back to it;
`raw/` is the investigation (numbered reports, measurements, diagrams), the rest of this directory is the result.

> [!WARNING]
> **Most of this has not been confirmed by a person yet.** The review was done with an AI coding agent: the agent read
> the source code of Kramerius, Akubra and process-platform, ran read-only queries against MZK production data, and
> decided what is a defect and what to propose. There are many findings (73 entries, 53 of them about a specific defect or code-level cost), and so far it
> has not been possible to confirm them other than in this agentic way:
>
> - **No entry is marked as confirmed by an MZK programmer yet** (`mzk_programmer_check` is empty on all of them).
> - **No test has been run** for any defect; where a test is described, it is a proposal.
> - **21 of them are known from code only**, and say so at the top of their evidence section. 29 were also looked for in
>   production data, and 14 match an incident reported in an upstream issue.
> - Line numbers refer to the named commits, which may differ from the deployed images.
>
> Treat every entry as a well-documented lead to check, not as a verified fact. Each defect's `checked` and `checked_how`
> fields say exactly what was done; see [Checked](#checked).

Every entry sits in the directory of its **category** (below), and its ID prefix names that category. Each category has
a template: [`_template-perf.md`](_template-perf.md) for `PS`, `PM` and `PH`, [`_template-qol.md`](_template-qol.md) for
`QOL`, [`_template-bug.md`](_template-bug.md) for `BUG` and `WC`, and [`_template-known-bug.md`](_template-known-bug.md) for `KB`.
`review_ref` links a defect to the review's `B` numbers, and `area` names the part of the code an entry touches.

Within a category, numbers follow priority as of 2026-10-28: higher severity or impact first, then lower effort. New entries
take the next free number in their category. IDs never change and are never reused. An entry that moves to another
category gets a new ID there and records the old one in `former_id`.

## Categories

The category says what fixing an entry gives and what to do with it next.

| Category | Directory, ID | Meaning | Next step |
| --- | --- | --- | --- |
| `perf-simple` | `perf-simple/`, `PS-` | Makes Kramerius faster or cheaper to run, with effort **XS–S**: one module, no new configuration, API or schema. | Open a pull request. |
| `perf-medium` | `perf-medium/`, `PM-` | The same, with effort **M**: a new component or configuration, still within one module. | Agree on the design, then a staging run under load. |
| `perf-hard` | `perf-hard/`, `PH-` | The same, with effort **L–XL**: a contract, storage format or several systems change. | Benchmark against a baseline, then decide. |
| `quality-of-life` | `quality-of-life/`, `QOL-` | Nothing returns a wrong result and nothing is measurably slow, but Kramerius becomes easier to run, observe, diagnose or develop: cleanup, telemetry, deployment, module structure, operational safety. | Discuss with maintainers; no urgency. |
| `bug` | `bugs/`, `BUG-` | Something does the wrong thing (wrong result, lost or stale data, failed request or job, wrong status, a failure reported as success), and no upstream issue reports it yet. | Open a new upstream issue. |
| `known-bug` | `known-bugs/`, `KB-` | An upstream issue already reports the same symptom; the entry adds what the issue lacks: the cause, a fix, production counts or a second path. | Comment on that issue. |
| `webclient-bug` | `webclient-bugs/`, `WC-` | A defect in the Kramerius web client (`kramerius-web-client-v3`), not in Kramerius or its components. `bugs/` and `known-bugs/` hold only Kramerius and its components. | Open an issue in the web client's repository. |

When an entry fits two categories, the first matching rule wins:

1. The defect is in the web client → `webclient-bug`.
2. An upstream issue reports the same symptom (not just a related one) → `known-bug`.
3. Something does the wrong thing → `bug`, even when the fix also speeds things up (e.g. BUG-015's failing PDFs).
4. The gain is time, load or storage → `perf-*`, with the tier taken from the entry's main effort, not its cheapest first step.
5. Otherwise → `quality-of-life`.

## Checked

Every defect entry (`BUG`, `KB`, `WC`, and the former bugs now under `PS` and `QOL`) records how it was confirmed:

| Field | Meaning |
| --- | --- |
| `checked` | the methods used: `source` (code read at a named revision), `test` (a test was run and failed before the fix), `production` (MZK logs, traces, databases or NGINX, read-only), `upstream-report` (an upstream issue reports the incident) |
| `checked_how` | one line: what was read, run or counted, at which revision; a test that is written but not run is said so here, not counted as `test` |
| `checked_on` | the date of the last check |
| `mzk_programmer_check` | who confirmed the defect, when and how (read the code, reproduced it, saw it in production), once an MZK programmer has; `null` until then. Entries known only from code also say so at the top of their evidence section. |

`production` means we looked, not that it was found: `checked_how` says what the look showed. As of 2026-10-28 no entry has
`test`: the tests for BUG-002 and BUG-004 are written but not run.

## Effort

Effort is a size, not a time estimate. It is set by **what has to change**, so anyone can check it against
the code. An entry takes the **highest** size whose criteria it meets.

| Size | What changes | Verification needed |
| --- | --- | --- |
| **XS** | A few lines in one method or class. No behavior change beyond the defect. | One unit test. |
| **S** | One or a few classes in one module. No new configuration, API, schema or data change. | Unit tests. |
| **M** | A new component (thread, queue, cache, client) or several classes, still within one module. New configuration, or a behavior change people notice (e.g. delayed logs). | Staging run under load. |
| **L** | Several modules, or a contract changes: REST API, Solr schema, storage format, DB schema. Needs backward compatibility or a migration path. | Benchmark against a baseline, plus a rollback plan. |
| **XL** | Several systems (Kramerius, Akubra, process-platform, deployment), or the repository or index must be migrated. Needs a staged rollout and coordination with other institutions or CDK. | Benchmark campaign, plus a migration rehearsal. |

The header fields `touches`, `contracts` and `data_migration` record the facts the size is based on.


## Simple performance improvements

| ID | Change | Impact | Effort | Seen in production / use cases |
| --- | --- | --- | --- | --- |
| [PS-001](perf-simple/PS-001-forward-resource-graph-per-request.md) | Every CDK forward request builds two new HTTP clients and the whole forward resource graph before any forward code runs | high | S | yes, two `Client.create()` per forward request = 52% of forward time (warm) |
| [PS-002](perf-simple/PS-002-rights-check-refetches-solr-doc.md) | Every rights check fetches the same Solr document again for each licence it evaluates | high | S | yes, ~3.9 identical Solr GETs per check; rights = half of direct IIIF time (warm) |
| [PS-003](perf-simple/PS-003-cdk-cache-key-omits-user.md) | The CDK request cache keys rows without the user, so its per-user cache holds one user per library, and expired rows are never deleted | medium | S (pruning job: M) | yes, 1 `forward/user` row for each of 14 libraries; `query_cache` 111 GB, 33.5 % expired |
| [PS-004](perf-simple/PS-004-desirable-table-written-never-read.md) | Every PDF page and Zoomify request writes a "most desirable" row that nothing reads, after an extra RELS-EXT read | low | XS | yes, 982k rows since 2026-05-18 (~150–225k a month), never read |
| [PS-005](perf-simple/PS-005-folder-list-queries-users-per-folder.md) | Listing a user's folders runs one more SQL query, on a second connection, for every folder | low | XS | not measured; source only |
| [PS-006](perf-simple/PS-006-deepzoom-original-global-lock.md) | Reading a cached deep-zoom original holds one lock for the whole instance, so concurrent Zoomify and deep-zoom requests read and decode images one at a time | unknown | XS | legacy image routes had no traffic in one warm window; deep-zoom cache use not checked |

## Medium performance improvements

| ID | Change | Impact | Effort | Seen in production / use cases |
| --- | --- | --- | --- | --- |
| [PM-001](perf-medium/PM-001-read-once-then-prefetch.md) | Read each object's FOXML once during indexing, then prefetch the next pages in parallel | high | M (read once: S) | use cases: indexing |
| [PM-002](perf-medium/PM-002-coalesce-reads-per-unit-of-work.md) | Collect the reads of one unit of work, join same-shaped queries into one, and wait for the rest on one barrier | high | M (joined queries in the indexer: S) | use cases: indexing, image-open, admin |
| [PM-003](perf-medium/PM-003-batched-access-log-writer.md) | Move IIIF access logging off the request thread | medium | M | use cases: image-open |
| [PM-004](perf-medium/PM-004-batch-solr-writes-in-indexer.md) | Send indexed documents to Solr in batches, without the XML round trip and the per-title commit | medium | M (commit flag: XS) | use cases: indexing |
| [PM-005](perf-medium/PM-005-elasticsearch-vs-solr.md) | Keep Solr for now; fix how Kramerius uses it, and make the search API engine-neutral before any switch | medium | M (switch: XL) | use cases: search, indexing, admin |

## Difficult performance improvements

| ID | Change | Impact | Effort | Seen in production / use cases |
| --- | --- | --- | --- | --- |
| [PH-001](perf-hard/PH-001-cache-by-invalidation-need.md) | Add caches in two tiers, split by whether they need invalidation on write | high | L (tier A: S) | use cases: image-open, search, admin |
| [PH-002](perf-hard/PH-002-group-foxml-and-ocr-per-parent.md) | Store FOXML and OCR in zstd-compressed groups per parent (issue, volume, monograph), with a short-lived cache of unpacked groups; compress ALTO per file | high | XL (per-file zstd: M) | use cases: indexing, image-open, storage, ingest |
| [PH-003](perf-hard/PH-003-storage-backend-options.md) | Compare storage backends for Akubra; the strongest change is FOXML and relations in PostgreSQL, with large datastreams kept on files or S3 | high | XL (benchmark: S) | use cases: indexing, image-open, ingest, admin, storage |
| [PH-004](perf-hard/PH-004-s3-blob-store-under-akubra.md) | Put an S3-compatible blob store under Akubra, only after repeated FOXML reads are removed | unknown | XL | use cases: image-open, indexing, ingest, admin, storage |

## Quality of life

| ID | Change | Impact | Effort | Seen in production / use cases |
| --- | --- | --- | --- | --- |
| [QOL-001](quality-of-life/QOL-001-otel-in-images-replace-monitor-core.md) | Ship OpenTelemetry in the Kramerius images with tested defaults, and retire the hand-written API monitor and its Solr core | high | L (sync write removal: XS) | use cases: image-open, search, indexing, ingest, admin |
| [QOL-002](quality-of-life/QOL-002-modularize-in-four-levels.md) | Make Kramerius modular in four levels: narrow interfaces, Java modules in one image, public and curator apart, then separate processes where measured | high | XL (level 1: L) | use cases: admin, search, image-open, indexing, ingest |
| [QOL-002.1](quality-of-life/QOL-002.1-narrow-interfaces.md) | Level 1: give each caller only the interface it needs, so readers cannot write and only the indexer writes Solr | medium | L (reader only: M) | use cases: admin, search, image-open, indexing |
| [QOL-002.2](quality-of-life/QOL-002.2-java-modules-one-image.md) | Level 2: cut shared:common into a small kernel and feature modules, still built into one Kramerius image | medium | L | use cases: admin, search, image-open, indexing |
| [QOL-002.3](quality-of-life/QOL-002.3-public-and-curator-apart.md) | Level 3: run public and curator with only their own code, first by a runtime role switch, then as separate images, with an all-in-one stack for CI | medium | L (admin-route filter: S) | use cases: admin, search, image-open |
| [QOL-002.4](quality-of-life/QOL-002.4-separate-processes-where-measured.md) | Level 4: move only coarse, rare or asynchronous parts into separate processes, starting with the statistics writer | unknown | XL (statistics writer: M) | use cases: image-open, indexing, admin |
| [QOL-003](quality-of-life/QOL-003-central-error-tracking-for-libraries.md) | Run a central, MZK-managed error-tracking service that Kramerius libraries can join, grouping the same bug across installations | high | XL (central service: M) | use cases: image-open, search, indexing, ingest, admin |
| [QOL-004](quality-of-life/QOL-004-worker-initiated-control.md) | Let workers initiate all manager–worker traffic, using a heartbeat lease instead of manager probes | medium | L | use cases: indexing, ingest, admin |
| [QOL-005](quality-of-life/QOL-005-per-client-rate-limit-identity.md) | Build per-client, per-endpoint rate limiting into Kramerius, keyed by a combination of user, HTTP headers and IP | medium | L | use cases: search, image-open, admin |
| [QOL-006](quality-of-life/QOL-006-web-xml-declares-deleted-servlets.md) | web.xml still declares the deleted servlets behind /fullThumb and /pdf, so Tomcat logs ClassNotFoundException and those URLs cannot work | low | XS | yes, 62 log lines in 7 days (public and curator), in pairs |
| [QOL-007](quality-of-life/QOL-007-one-implementation-per-curator-write.md) | Give each kind of curator write one implementation and one execution rule, decided by what the write touches | high | L | use cases: admin, indexing, ingest |
| [QOL-008](quality-of-life/QOL-008-one-foxml-parsing-layer.md) | Give FOXML one parsing layer in Akubra, with shared parser factories and one parsed model that callers project from | unknown | L (shared factories: S) | use cases: image-open, indexing, admin, ingest |

## Bugs

| ID | Bug | Severity | Effort | Review | Seen in production |
| --- | --- | --- | --- | --- | --- |
| [BUG-001](bugs/BUG-001-thumbnail-replace-deletes-object.md) | Setting a title's or collection's thumbnail deletes the whole object and ingests it again, so a failure in between loses the object | high | XS | B20 | not yet observed; source only |
| [BUG-002](bugs/BUG-002-unmarshaller-pool-leaks-on-error.md) | Each FOXML that fails to parse removes one unmarshaller from Akubra's pool of 50, and when the pool is empty every write and export in that JVM hangs | high | XS | B17 | not yet observed; 5 malformed FOXML exist at MZK |
| [BUG-003](bugs/BUG-003-model-reindex-hides-page-errors.md) | The model-wide reindex reports a title as indexed even when some of its pages failed, and clears the title's "indexation in progress" marker | high | XS | B15 | not yet counted; source only |
| [BUG-004](bugs/BUG-004-lock-client-race-sets-read-only.md) | Parallel admin writes on a freshly started pod fail while the lock client is still connecting, and each failure switches the whole instance to read-only | high | XS | — | yes, 2026-10-28: 10 failed deletes in 2 s on both curators, instance went read-only; lock server healthy |
| [BUG-005](bugs/BUG-005-delete-tree-ignores-child-failures.md) | Delete-tree job ignores failed descendants in its result | high | XS | H4 | source only; plugin used 69 times in 30 days |
| [BUG-006](bugs/BUG-006-reharvest-closes-failed-job.md) | CDK reharvest worker closes queue item after a failed job | high | XS | H9 | source only |
| [BUG-007](bugs/BUG-007-akubra-swallows-storage-errors.md) | Akubra logs and ignores failed saves and deletes, so callers and the processing index go on as if they succeeded | high | S | B9 | not yet counted; needs worker and curator logs |
| [BUG-008](bugs/BUG-008-import-schedule-failure-reports-success.md) | FOXML import reports success after child indexing cannot be scheduled | high | S | H1 | source only |
| [BUG-009](bugs/BUG-009-reharvest-register-reports-success-after-solr-failure.md) | CDK reharvest registration reports success after a Solr write failure | high | S | H10 | source only |
| [BUG-010](bugs/BUG-010-processing-index-submits-partial-rebuild.md) | Processing-index rebuild submits partial relations after an error | high | S | H11 | source only |
| [BUG-011](bugs/BUG-011-reharvest-scheduling-loses-process-link.md) | CDK reharvest scheduling can lose the process link after job creation | high | XL | H8 | source only |
| [BUG-012](bugs/BUG-012-dc-less-ancestor-npe.md) | Access log crashes and writes partial records when an ancestor has no DC | medium | XS | B13 | yes, ~37–40% of `info.json` requests (warm, 2026-10-28; 25k NPEs in 7.5 h) |
| [BUG-013](bugs/BUG-013-ocr-dropped-on-invalid-xml-char.md) | A page with one invalid control character in its OCR is indexed with no full text at all | medium | XS | — | code comment shows it occurred; not counted |
| [BUG-014](bugs/BUG-014-gc-fails-running-job-on-one-probe-error.md) | The process manager marks a job FAILED after one failed status call to its worker | medium | XS | B8 | not yet observed |
| [BUG-015](bugs/BUG-015-pdf-font-scan-per-request.md) | Every PDF request rescans all font directories into iText's global font registry, and concurrent PDFs fail with ConcurrentModificationException | medium | XS | — | yes, 831 CME log lines in 7 days, all in PDF selection |
| [BUG-016](bugs/BUG-016-export-fails-on-file-referenced-streams.md) | Exporting an object fails to include managed datastreams referenced by a file URL, even when the file exists | medium | XS | — | yes, 110 export errors in 7 days on objects whose files were present |
| [BUG-017](bugs/BUG-017-search-solr-400-returned-as-500.md) | The search API answers 500 when Solr rejects a query, because it catches the wrong HttpResponseException class | medium | XS | B11 | yes, ~8,900 search 500s in 7 days, ~3/4 of them Solr 400s |
| [BUG-018](bugs/BUG-018-pdf-extractor-never-closed.md) | Indexing a PDF object never closes the PDF, so a job over many PDFs keeps every document, file handle and temp copy until its JVM exits | medium | XS | B5 | yes, 411 temp copies (1.8 GB) in 3 min of one tree reindex, freed only at JVM exit; 13,832 PDF objects at MZK |
| [BUG-019](bugs/BUG-019-import-list-skips-missing-directories.md) | FOXML import list omits unavailable directories while reporting success | medium | XS | H3 | source only |
| [BUG-021](bugs/BUG-021-kill-overwritten-by-late-report.md) | Killing a batch does not stop a job that is still starting; its RUNNING report overwrites KILLED | medium | S | B25 | not yet observed |
| [BUG-022](bugs/BUG-022-claimed-job-stranded-not-running.md) | A job that a worker claimed but never started stays NOT_RUNNING for good, and nothing retries or fails it | medium | S | B7 | yes, 2 of 41,814 MZK jobs stuck since 2026-10-01 and 2026-10-07 |
| [BUG-023](bugs/BUG-023-search-default-field-does-not-exist.md) | The Solr search configs set the default field to "text", which no Kramerius schema defines, so any unfielded query word fails | medium | S | — | yes, 9,874 `undefined field text` in 7 days; 54% of ungrouped multi-word in-document searches fail |
| [BUG-024](bugs/BUG-024-import-merge-ignores-relation-write-failure.md) | FOXML merge ignores failed relation writes | medium | S | H2 | source only |
| [BUG-025](bugs/BUG-025-processing-index-backfill-stops-at-1000.md) | Processing-index stream backfill stops after 1,000 relations | medium | S | H6 | source only |
| [BUG-026](bugs/BUG-026-iiif-500-for-objects-without-tiles.md) | The IIIF endpoint answers 500 and logs SEVERE for objects that have no IIIF image, instead of 404 | low | XS | — | yes, 100 log lines for 69 objects in 7 days; 1 page where items/info and IIIF disagree |
| [BUG-028](bugs/BUG-028-pdf-endpoints-leave-streams-open.md) | The PDF endpoints never close the three output streams they open per request, and leave the rendered file behind when generation fails | low | XS | — | not seen; one public pod had no leftover PDF temp files at one instant |
| [BUG-029](bugs/BUG-029-statistics-semaphore-gains-permit-on-interrupt.md) | The statistics report's one-at-a-time semaphore gains a permit each time a waiting request is interrupted | low | XS | — | not observed; source only |
| [BUG-030](bugs/BUG-030-iiif-tiles-fail-until-restart-after-cluster-disruption.md) | After a cluster disruption, kramerius-public answers 500 for most IIIF tiles until it is restarted, while staying Ready | high | M | — | yes, 52,523 tile 500s on 2026-10-29 02:50–07:53Z (67–82 % of tiles per hour), ended by a manual restart |

## Web client bugs

| ID | Bug | Severity | Effort | Review | Seen in production |
| --- | --- | --- | --- | --- | --- |
| [WC-001](webclient-bugs/WC-001-web-cache-rounds-api-values.md) | Web client cache rounds numbers in large API responses | medium | XS | H7 | source only |

## Known bugs: more information for upstream issues

| ID | Bug | Upstream issue | Severity | Effort | What this entry adds |
| --- | --- | --- | --- | --- | --- |
| [KB-001](known-bugs/KB-001-process-gc-stops-forever.md) | The process manager's GC stops for good after one exception, so dead jobs stay "Running" | [process-platform#15](https://github.com/ceskaexpedice/process-platform/issues/15) | high | XS | One cause of jobs stuck as Running: the GC task stops for good after one exception |
| [KB-002](known-bugs/KB-002-worker-loop-stops-on-poll-error.md) | A worker stops taking jobs for good after one failed poll to the process manager | [process-platform#13](https://github.com/ceskaexpedice/process-platform/issues/13) | high | XS | Cause in the worker poll loop; 2026-10-28 all 10 MZK worker loops exited, ~9.5 h without jobs |
| [KB-003](known-bugs/KB-003-cdk-probes-info-json-per-tile.md) | Every image opened through the CDK is counted as dozens of views in the source library's statistics | [kramerius#1362](https://github.com/ceskaexpedice/kramerius/issues/1362) | high | S | Cause (the CDK probes `info.json` per tile) and fix; 17–34 views recorded per single open at MZK |
| [KB-004](known-bugs/KB-004-relsext-update-writes-object-twice.md) | Updating RELS-EXT saves the object twice, first without RELS-EXT, so a crash in between deletes it for good | [process-platform#14](https://github.com/ceskaexpedice/process-platform/issues/14) | high | S | Cause: the object is saved without RELS-EXT, then again with it; earlier report kramerius#994 (closed) |
| [KB-005](known-bugs/KB-005-worker-never-starts-if-registration-fails.md) | A worker that cannot register with the process manager at startup never takes a job, while its pod looks healthy | [process-platform#13](https://github.com/ceskaexpedice/process-platform/issues/13) | high | S | Second path to the same symptom: registration fails at startup; 5 of 10 MZK pods after a deploy |
| [KB-006](known-bugs/KB-006-import-leaves-file-referenced-managed-streams.md) | FOXML import leaves file-referenced managed OCR and ALTO outside Akubra | [kramerius#1138](https://github.com/ceskaexpedice/kramerius/issues/1138) | high | S | Cause confirmed: Akubra copies only inline managed content, not file references |
| [KB-007](known-bugs/KB-007-delete-import-not-serialized-per-tree.md) | Delete-tree and import jobs are not serialized for the same object tree | [kramerius#1332](https://github.com/ceskaexpedice/kramerius/issues/1332) | high | L | Cause confirmed: per-PID locks only, nothing serializes a whole tree |
| [KB-008](known-bugs/KB-008-alto-rotation-uppercase-pdf-500.md) | PDF generation fails when ALTO specifies uppercase ROTATION | [kramerius#1333](https://github.com/ceskaexpedice/kramerius/issues/1333) | medium | XS | Found independently; exact line of the case mismatch; 3 PDF 500 traces at MZK |
| [KB-009](known-bugs/KB-009-child-stream-facet-false-ocr-flags.md) | Zero-count child stream facets set OCR and ALTO flags to true | [kramerius#1356](https://github.com/ceskaexpedice/kramerius/issues/1356) | medium | XS | Cause confirmed: facet terms with count 0 are turned into OCR/ALTO flags |
| [KB-010](known-bugs/KB-010-invalid-mods-uuid-overwrites-valid-uuid.md) | An invalid empty MODS UUID can replace a valid identifier during NDK import | [kramerius#1312](https://github.com/ceskaexpedice/kramerius/issues/1312) | medium | XS | Cause confirmed: an empty UUID is accepted and overwrites the valid one |
| [KB-011](known-bugs/KB-011-public-worker-pdf-has-no-alto-text.md) | Public worker PDF generation disables the ALTO text layer | [kramerius#1338](https://github.com/ceskaexpedice/kramerius/issues/1338) | medium | XS | Cause confirmed: the public worker's PDF service switches ALTO off |
| [KB-012](known-bugs/KB-012-internalize-file-referenced-streams.md) | Copy file-referenced managed datastreams into Akubra on ingest, as Fedora did, and repair the objects that still point to import folders | [kramerius#1138](https://github.com/ceskaexpedice/kramerius/issues/1138) | medium | S (repair job: M) | The fix and a repair job for objects already stored with file references (defect: KB-006) |
| [KB-013](known-bugs/KB-013-keycloak-login-rewrites-roles.md) | Every new session of a Keycloak user deletes and re-inserts all its roles, even when nothing changed | [kramerius#1231](https://github.com/ceskaexpedice/kramerius/issues/1231) | medium | S | MZK counts (210k inserts, 208k deletes on `group_user_assoc`) and a fix that writes only changed roles |
| [KB-014](known-bugs/KB-014-image-stream-reads-first-version.md) | Thumbnail and preview reads use the first external datastream version | [kramerius#1287](https://github.com/ceskaexpedice/kramerius/issues/1287) | medium | S | Cause confirmed at current Akubra: the reader stops at the first `contentLocation` |
| [KB-015](known-bugs/KB-015-datecreated-not-indexed.md) | Date indexing omits MODS dateCreated | [kramerius#1348](https://github.com/ceskaexpedice/kramerius/issues/1348) | medium | S | Cause confirmed: `DateExtractor` never reads `dateCreated` |
| [KB-016](known-bugs/KB-016-folder-counts-and-orphans-after-delete.md) | Removing items from a folder never lowers its item count, and deleting a folder leaves its items behind | [kramerius#1300](https://github.com/ceskaexpedice/kramerius/issues/1300) | low | S | Also orphan items after folder delete; 48 wrong counts and 233 orphans at MZK; reconcile SQL |
| [KB-017](known-bugs/KB-017-import-inventory-keeps-every-foxml.md) | FOXML import parses the whole package into memory before importing, so a large package runs the worker out of heap | [kramerius#1364](https://github.com/ceskaexpedice/kramerius/issues/1364) | medium | S | Cause: `ImportInventoryFactory.loadDigitalObjects` keeps every parsed object; fix: keep only inventory fields |
