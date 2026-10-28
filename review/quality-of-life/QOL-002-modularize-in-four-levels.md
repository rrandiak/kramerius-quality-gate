---
id: QOL-002
former_id: IDEA-010
category: quality-of-life
title: Make Kramerius modular in four levels - narrow interfaces, Java modules in one image, public and curator apart, then separate processes where measured
area: modularization
impact: high             # testability, failure isolation, sustainable upgrades; no direct speed gain
effort: XL               # level 1 L, level 2 L, level 3 L, level 4 XL
touches: [kramerius (shared:common, rest, search, folders, processes), akubra (read/write interfaces), kramerius-helm-chart, docker compose examples]
contracts: [config, api]
data_migration: false
use_cases: [admin, search, image-open, indexing, ingest]
review: [09-service-boundaries, 11-deployment-incident-check, 17-curator-write-boundaries, 18-folders-source-audit, 20-rights-boundary, 21-repository-boundary, 22-processing-boundary, 23-public-boundary]
upstream: null
---

# QOL-002 — Make Kramerius modular in four levels: narrow interfaces, Java modules in one image, public and curator apart, then separate processes where measured

> **In one sentence:** first give each caller only the interface it needs (readers cannot write), then cut the 509-class
> `shared:common` into a small common kernel plus feature modules while still building one image, then run public and
> curator with only their own code, and only then move parts that are coarse, rare or asynchronous into separate
> processes, each level useful on its own.

## Today

Kramerius `origin/master` `560676c`, Akubra `51d821b`, process-platform `976dc4b`.

**Deployment is split by role; the code is not.** MZK runs `krameriusPublic` (2 replicas) and `krameriusCurator`
(2 replicas) from the same image (`kramerius:7.2.2.4`, same digest), a process manager and three worker groups
(MZK deployment values). The gateway sends `/search/api/admin/` to curator and everything else to public
([deployment check](../raw/11-deployment-incident-check.md)).

**One web WAR and one shared module.** The `search` WAR depends on `rest`, `shared:common`, `security:*` and several process
modules, some marked `//TODO: Delete` or `//TODO: Move` (`search/build.gradle:55–60`). `ApiServletModule.configureServlets`
binds client, CDK, admin, OAI and folders resources in one Guice module (`rest/.../api/guice/ApiServletModule.java:98–250`);
admin resources (from line 182) are bound in every pod. Only the CDK resources depend on a setting, `cdk.server.mode`
(line 103). `shared:common` has 509 main classes (and 77 test classes); every web pod and every plugin JVM loads all of it.

**No way to run the whole system locally** for integration tests: [BUG-002](../bugs/BUG-002-unmarshaller-pool-leaks-on-error.md)'s
test could not be run without a cluster.

## Questions and answers

### Q1. What is actually common?

Measured by which consumers import each part of `shared:common` (files that import it; source at `560676c`):

| Part | Classes | public API | admin API | CDK API | search WAR | plugins | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| repository (Akubra API, external) | — | 20 | 7 | 4 | 16 | 24 | **common** |
| index read (`SolrAccess`, already an interface) | 1 | 44 | 7 | 4 | 9 | 5 | **common** |
| object model (root package: `ObjectPidsPath`, `KrameriusModels`, `Constants`, …) | 11 | 53 | 19 | 4 | 14 | 6 | **common** |
| configuration and utilities (`utils`) | 62 | 70 | 19 | 6 | 29 | 80 | **common**, once cleaned (Q3) |
| security: user, rights decision | 109 | 42 | 23 | 6 | 24 | 5 | **common contract**; administration and criteria are features |
| `database`, `users` | 17 + 12 | 4 | 0 | 1 | 10 | 0 | web roles only |
| index write (`solr`, `fedora`, `dochub`) | 4 + 5 + 13 | 4 | 0 | 0 | 3 | 49 | **indexer** feature |
| statistics | 59 | 5 | 1 | 4 | 7 | 18 | **statistics** feature (capture in public, reports in plugins) |
| documents and media (`pdf`, `printing`, `document`, `imaging`, `audio`, `cz.knav.pdf`) | 101 | 12 | 0 | 2 | 15 | 5 | **documents** feature, public only |
| CDK cache (`cz.inovatika.cdk`, `cdk`) | 10 | 23 | 1 | 0 | 3 | 3 (CDK plugins) | **CDK** feature |
| `uiconfig`, `workmode`, `processes`, `monitoring` | 13 + 8 + 20 + 2 | — | — | — | — | — | small features, one or two consumers each |
| `virtualcollections`, `cz.inovatika.http` | 5 + 1 | 0 | 0 | 0 | 0 | 0 | used only inside `shared:common`; check before deleting |

**Answer:** the common kernel is small: the object model, configuration and pure utilities, the repository interface, the
index-read interface, and the security contract (who the user is, and "may this user do this action on this object").
Everything else has one main consumer and is a feature module.
**Why:** the table. The parts most of the code base imports are exactly these; the large blocks (documents 101 classes,
statistics 59, index write 22) each serve one side.

### Q2. Does Kramerius need more interfaces?

The first guess was "too many concrete classes". Measured, it is not: of 105 `new …Impl(` calls outside Guice modules,
almost all create value objects (`LicenseImpl` 17, `RoleImpl` 16, path objects 13, `UserImpl` 9); services are already
injected by Guice, with 14 `getInstance(X.class)` lookups left in plugins.

The real gap is **width and direction**:

| Caller | Akubra methods used | Writes | Gets |
| --- | --- | --- | --- |
| public API | 14 distinct, 82 calls | 0 | the full read/write `AkubraRepository` |
| CDK API | 5 distinct, 7 calls | 0 | the full read/write `AkubraRepository` |
| search WAR | 8 distinct, 50 calls | 0 | the full read/write `AkubraRepository` |
| admin API | 30 distinct, 124 calls | 11 distinct, 47 calls, including `pi().commit`, `re().update`, `doWithLock`, `delete`, `ingest` | the full interface, and orchestrates low-level writes itself |
| plugins | 43 distinct, 157 calls | 15 distinct, 49 calls | the full interface |

Besides the repository, admin handlers write the search index directly (`SearchIndexHelper`,
`ItemsResource.deleteFromSearchIndex`, `CollectionsResource`), and `SecuredAkubraRepositoryImpl`, the repository with rights
checks, lives inside the `security` package.

**Answer:** not more interfaces but **narrower** ones: a read interface for readers, an intent-level write interface for
writers, an index writer that only the indexer holds. That is [level 1](QOL-002.1-narrow-interfaces.md).

### Q3. Modules by layer or by feature?

| Option | For | Against |
| --- | --- | --- |
| By layer (`api`, `impl`, `rest`) | familiar | every feature change touches every module; does not let an image leave a feature out |
| **By feature, with a small API kernel** | an image can leave a feature out; a feature has one owner | needs the cycles below broken first |

**Answer:** a kernel of API modules (Q1) and feature modules on top. That is [level 2](QOL-002.2-java-modules-one-image.md).
**Before it can be cut**, the package cycles must go: `security` ↔ `service`, `security` ↔ `users`, `security` ↔ root
package; `utils` imports `service`, `document`, `solr` and `impl` (through `DCUtils`, `IterationUtils`, `utils/solr/SolrUtils`);
`security` imports `dochub`, `virtualcollections` and `biz`.

### Q4. Public and curator: separated at runtime or at build time?

| Option | For | Against |
| --- | --- | --- |
| **Runtime role switch first** (one image, `KRAMERIUS_ROLES`) | small; the pattern exists (`cdk.server.mode`); libraries with one pod keep all roles | admin code stays in the public image, only inactive |
| Build-time images per role | public image has no admin code | needs level 2's modules first |

**Answer:** runtime switch first, build-time images once level 2 exists. That is [level 3](QOL-002.3-public-and-curator-apart.md).

### Q5. What may run as a separate process?

**Answer:** only what is coarse, rare or asynchronous; the hot paths stay in-process. Rules in
[level 4](QOL-002.4-separate-processes-where-measured.md):

| Part | How often | Verdict |
| --- | --- | --- |
| rights | every image, tile and item request (~26 ms per check warm, half of a direct IIIF request) | in-process |
| repository reads | ~4 FOXML reads and 2 processing-index queries per indexed page; several per public request | in-process; a service only with batched calls and [PH-003](../perf-hard/PH-003-storage-backend-options.md) |
| statistics writing | every `info.json` | separate, asynchronous |
| document generation | on request | already on workers |
| folders | a few calls per session | may run separately when a reason appears |

### Q6. Collections and folders: modules or services?

**Answer:** modules. Collections are repository objects plus search fields plus licence propagation, so a separate service
would add network failures to an already non-atomic sequence; the fix is [QOL-007](QOL-007-one-implementation-per-curator-write.md).
Folders are the cleanest boundary (own tables, public only) and the first candidate if anything is ever extracted, after
[KB-016](../known-bugs/KB-016-folder-counts-and-orphans-after-delete.md).

## Proposal

| Level | Entry | What changes | Build and deploy | Effort | Needs |
| --- | --- | --- | --- | --- | --- |
| **1** | [QOL-002.1](QOL-002.1-narrow-interfaces.md) Narrow interfaces | `RepositoryReader` for readers, `RepositoryWriter` with intent-level writes, `IndexWriter` only for the indexer, rights contract separate from the repository; package cycles broken; architecture tests | unchanged | L | nothing; [QOL-007](QOL-007-one-implementation-per-curator-write.md) helps |
| **2** | [QOL-002.2](QOL-002.2-java-modules-one-image.md) Java modules, one image | `shared:common` split into kernel and feature modules; plugins depend only on what they use | one WAR, one image | L | level 1 |
| **3** | [QOL-002.3](QOL-002.3-public-and-curator-apart.md) Public and curator apart | runtime role switch, then per-role images; CDK as a role; all-in-one Compose stack for CI | two images (or one with roles) | L | level 1; level 2 for per-role images |
| **4** | [QOL-002.4](QOL-002.4-separate-processes-where-measured.md) Separate processes where measured | statistics writer for all public pods; document generation out of the web image; folders or a repository service only with a measured need | more deployables | XL | level 2 |

Levels 1 and 2 change structure, not behavior: existing tests and architecture rules can show they are safe. Behavior
changes to curator writes belong to [QOL-007](QOL-007-one-implementation-per-curator-write.md), which can run in parallel.

## What gets easier

| Who | Today | After | Basis |
| --- | --- | --- | --- |
| reviewers | any class can write the repository or Solr | only holders of `RepositoryWriter` / `IndexWriter`, checked by tests | level 1 |
| plugin authors | a plugin JVM loads all 509 classes and their libraries | a plugin depends on the kernel and what it uses | level 2 |
| maintainers | a library upgrade touches everything at once | module by module (jakarta, newer libraries) | level 2 |
| operators | admin endpoints exist in public pods | not bound (level 3 runtime), absent (level 3 images) | `ApiServletModule.java:182` |
| developers and CI | integration tests need a cluster | `docker compose up` with the whole system | level 3 |
| readers of the site | statistics, PDF and pool problems share the reader's JVM | a failing statistics writer or PDF job does not touch reading | level 4 |

No change in request latency: hot paths stay in-process (Q5). Speed comes from the `PS`, `PM` and `PH` entries.

## Costs and risks

- Long, careful work in `shared:common`; without upstream agreement it becomes a fork.
- More modules and assemblies mean a larger build and test matrix.
- Every separate process adds operations work and a failure mode; Q5's rules must be enforced, not only written.

## Alternatives

1. **Do nothing.** One WAR, one large shared module, admin code in public pods, no local stack.
2. **Only harden routing** (block `/search/api/admin/` on public pods in the ingress and in the app). Small and worth doing
   at once, but leaves the code as it is.
3. **Microservices now** (repository, rights, collections as separate deployables). Adds network hops to the hottest paths
   and to non-atomic writes; rejected by Q5 and Q6.

## Effort

**Size: XL** in total, delivered by level; each level has its own effort table.

| Part | Size | Why this size |
| --- | --- | --- |
| Level 1 | L | many modules change their imports; no build or deploy change |
| Level 2 | L | Gradle restructure across all modules |
| Level 3 | L | Guice module split, chart and Compose changes |
| Level 4 | XL | new deployables, a queue, possibly a repository service with PH-003 |

## How we know it worked

1. Level 1: an architecture test fails if a public, CDK or search-WAR class imports `RepositoryWriter`, `IndexWriter` or
   `AkubraRepository`.
2. Level 2: a plugin's runtime classpath lists only the kernel and its own features; no package cycle across modules.
3. Level 3: every admin route returns 404 on a public pod; the all-in-one stack runs the integration suite in CI.
4. Level 4: with the statistics writer stopped for an hour on staging, `info.json` latency and errors do not change.

## Open questions

- Will upstream maintainers accept the kernel and feature-module layout, and who owns which module?
- Should the read and write interfaces live in Akubra (so all callers get them) or in Kramerius as a wrapper first?
- Are other libraries running public and curator as separate deployments, or one pod for both?
