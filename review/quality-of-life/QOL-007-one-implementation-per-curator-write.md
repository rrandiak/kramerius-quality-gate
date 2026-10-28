---
id: QOL-007
former_id: null
category: quality-of-life
title: Give each kind of curator write one implementation and one execution rule, decided by what the write touches
area: modularization
impact: high             # removes the shared cause of several data-loss and stale-index bugs; no speed gain
effort: L                # admin handlers, delete-tree plugin, collections, Akubra write calls; no storage format change
touches: [kramerius (rest admin v70, processes delete-tree, collections), akubra (write calls only)]
contracts: [api]
data_migration: false
use_cases: [admin, indexing, ingest]
review: [17-curator-write-boundaries, 21-repository-boundary, 22-processing-boundary]
upstream: null
---

# QOL-007 — Give each kind of curator write one implementation and one execution rule, decided by what the write touches

> **In one sentence:** sort every curator write by what it touches (one setting, one object, many objects, or a raw
> repair), give each class one execution rule (synchronous, synchronous plus a reindex job, or a job with a record and
> retries), and give each operation one implementation that the REST handler and the batch plugin both call, as licences
> already do.

## Today

Kramerius `origin/master` `560676c`, Akubra `51d821b`. The admin API (`rest/.../apiNew/admin/v70/`) has 65 `POST`, `PUT`
and `DELETE` methods. Leaving out process scheduling (`ProcessResource`, `CDKProcessResource`), statistics cleanup and two
read-only `POST`s in `ConfigResource`, they fall into four classes by what they touch:

| Class | Endpoints | What they touch | How they run |
| --- | --- | --- | --- |
| **A. Settings and accounts** | `ConfigResource`, `UIConfigResource`, `UIConfigContentResource`, `WorkModeResource`, `RightsResource`, `RolesResource`, `UsersResource`, `LicensesResource` (licence definitions), `ReharvestResource`, `ConnectedInfoResource` | one store (a DB table, a config file, the reharvest Solr core), nothing derived | synchronous |
| **B. One object, indexed data** | `ItemsResource`: `setChildrenOrder` (line 371), `streamHead` (726), `setImgThumb` (788), `setMODS` (863) | one object in Akubra; its search document (and for children order, its children's documents) depend on it | synchronous repository write; **no reindex**: the scheduling in `setChildrenOrder` is a commented-out `TODO` (line 430), `setMODS` only calls `updateXMLDatastream` (line 883) |
| **C. Many objects or derived state** | `CollectionsResource` (create, update, add/remove items, delete, clip items: lines 145–1257); licence add/remove; delete tree; import | RELS-EXT of several objects, the search index, licence fields | mixed: licences and delete tree are **jobs**; collections are **synchronous handlers** that write RELS-EXT under a lock, schedule reindex jobs, then write `contains_licenses` to Akubra and Solr, none atomic with the next ([run 17](../raw/17-curator-write-boundaries.md)) |
| **D. Raw repair tools** | `AkubraResource` `ingest`, `delete`, `create*Datastream`, `deleteDatastream` (lines 218–365); `ItemsResource.deleteObject` (463) | one object, with no derived updates on purpose | synchronous |

**Licences show the target pattern.** The admin API schedules `add_license` and the plugin reuses `SetLicenseProcess`:
one implementation, run as a job for one object or for a batch.

**Deletes.** There are two kinds, and that is right: the **delete-tree job** (`DeleteTreeProcess`) removes an object with
its descendants and is the normal curator path; a **low-level delete** removes one object and nothing else, for repairs.
The low-level delete exists twice, with different results:

| | `ItemsResource.deleteObject` (`ItemsResource.java:463–499`) | `AkubraResource.delete` (`akubra/AkubraResource.java:244–255`) |
| --- | --- | --- |
| Managed datastream data | deleted only for pages (`"page".equals(model)`, line 482), so a collection's shared thumbnail survives | always deleted (`delete(pid, true, true)`) |
| Relations pointing to it in the processing index | removed | removed |
| RELS-EXT of the parent | kept (documented in the method's Javadoc, lines 443–462) | kept |
| Search index | the object's document deleted (line 485) | kept, so search still finds a deleted object |

**Who writes the search index.** The indexer in the index plugins, and also admin handlers directly: `SearchIndexHelper`,
`ItemsResource.deleteFromSearchIndex`, `CollectionsResource` (licence fields).

**What goes wrong because of this** (each is its own entry):

| Entry | Class | Cause in this picture |
| --- | --- | --- |
| [BUG-001](../bugs/BUG-001-thumbnail-replace-deletes-object.md) | B | the thumbnail handler deletes and re-ingests the object |
| [KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md) | B, C | a RELS-EXT update saves the object twice |
| [BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md) | all | failed writes are logged and ignored, so the caller reports success |
| [BUG-005](../bugs/BUG-005-delete-tree-ignores-child-failures.md) | C | delete tree reports success after failed descendants |
| [KB-007](../known-bugs/KB-007-delete-import-not-serialized-per-tree.md) | C | delete tree and import are not serialized per tree |
| [KB-016](../known-bugs/KB-016-folder-counts-and-orphans-after-delete.md) | A (folders, public API) | folder writes are separate statements without a transaction |

## Questions and answers

### Q1. Should every curator write run as a job?

| Option | For | Against |
| --- | --- | --- |
| Always a job | one model, retries everywhere | a job for renaming a role or saving UI config is overhead with no gain |
| A job only for batches | simple rule | collection membership for one item still touches several objects and the index, and stays non-atomic |
| **Depends on what the write touches** | the rule follows the failure mode | needs a classification, kept up to date |

**Answer:** it depends on the class, with one rule per class:

| Class | Rule |
| --- | --- |
| A. Settings and accounts | **Synchronous, one transaction.** Nothing derived, so nothing to retry. |
| B. One object, indexed data | **Synchronous repository write, then a reindex job** for the affected scope, scheduled by the same operation. The response returns after the write, with the job ID. One save per change (no delete and re-ingest). |
| C. Many objects or derived state | **Always a job with an operation record**: steps, progress, retries, a final state that reports partial failure. The REST call for one object schedules the same job and may wait for it briefly. |
| D. Raw repair tools | **Synchronous, explicitly raw.** No derived updates, a separate permission, an audit log line, and the response says what was **not** updated. |

**Why:** the failures above come from class B and C writes run as synchronous multi-step handlers; class A writes have no
such reports, and making them jobs would add work without fixing anything.

### Q2. How many deletes should there be?

**Answer:** two, as today in intent: the delete-tree job (class C) and one low-level delete (class D). Merge the two
low-level endpoints into one, with the managed-data choice and the search-index removal as explicit parameters instead of
two different hidden defaults.
**Why:** a curator should not get a different result from the same action depending on which screen called which
endpoint; today `AkubraResource.delete` leaves a deleted object findable in search.

### Q3. Who may write the search index?

| Option | For | Against |
| --- | --- | --- |
| Anyone with a reason (today) | fast, no job needed | two code paths compute the same fields; a handler and a later reindex can disagree |
| **Only the indexer** | one place computes each field | a field change waits for a reindex job |

**Answer:** only the indexer. Handlers that set fields today (`contains_licenses` in collections) schedule a reindex of the
affected objects. The one exception is removing a deleted object's document, which the delete operation does itself.

### Q4. Where do operation records live?

**Answer:** in the process manager's database, as part of the job (its parameters, steps done, last error). No new store.
**Why:** class C operations already run as jobs; the process manager already persists their state and shows it to curators.

## Proposal

1. **Classify** every admin write endpoint into A–D in code (an annotation or a table checked by a test), so a new endpoint
   must choose.
2. **Class D:** merge the low-level deletes into one; give the raw `AkubraResource` operations their own permission and an
   audit line.
3. **Class B:** replace delete-and-ingest in `setImgThumb` with one datastream update (fixes BUG-001); schedule the reindex
   in `setChildrenOrder` (the commented-out `TODO`) and in `setMODS`.
4. **Class C:** turn collection membership, collection delete and clip items into jobs with one implementation each, as
   licences are; fix delete tree's result (BUG-005) and serialize it with import per tree (KB-007).
5. **Single index writer:** remove direct Solr writes from admin handlers (Q3).
6. Underneath all of it, writes must fail loudly ([BUG-007](../bugs/BUG-007-akubra-swallows-storage-errors.md)) and save
   once ([KB-004](../known-bugs/KB-004-relsext-update-writes-object-twice.md)).

This is independent of the modularization in [QOL-002](QOL-002-modularize-in-four-levels.md) and can start first. It gives
QOL-002's level 1 a clean `RepositoryWriter` to put behind an interface.

## What gets easier

| Who | Today | After | Basis |
| --- | --- | --- | --- |
| curators | a half-done collection change or thumbnail swap shows as success | a job with a visible state; failed steps can be retried | source |
| curators | the same delete gives different results on different screens | one low-level delete with stated effects, and delete tree for normal use | source |
| developers | a new admin write picks its own sequence of Akubra and Solr calls | it picks a class; the class decides the rule | design |
| operators | search can show deleted or stale objects after admin edits | each class B and C change ends with a reindex, or a recorded failure | source |

No change in request latency for readers.

## Costs and risks

- Class B and C changes become eventually consistent in search: the reindex job finishes after the response. The admin
  client must show that state.
- More jobs in the process manager, which has its own reliability gaps (KB-001, KB-002, BUG-014, BUG-022).
- Admin client changes for endpoints that now return a job ID.

## Alternatives

1. **Do nothing.** The bugs in the table keep their shared cause; each is fixed alone.
2. **Fix each bug alone.** Necessary anyway, but a new endpoint can repeat the same pattern.
3. **Everything as a job.** Simpler rule, but overhead for class A with no failure it would fix.

## Effort

**Size: L**, set by several modules and an API change (endpoints that return a job ID).

| Part | Size | Why this size |
| --- | --- | --- |
| Classification and its test | S | annotations or a table, one test |
| One low-level delete, permission, audit | S | two endpoints into one |
| Class B fixes (thumbnail, reindex scheduling) | S | three handlers |
| Collections and clip items as jobs | L | new plugins, admin client change |
| Delete tree result and per-tree serialization | M | BUG-005 is XS; KB-007 needs a tree lease |
| Single index writer | M | handlers schedule reindex instead of writing fields |

## How we know it worked

- A test fails when an admin write endpoint has no class.
- Fault injection on a local stack: a storage failure in the middle of each class C operation leaves the job FAILED with
  the step named, and a retry completes it.
- No admin handler imports a Solr update client (an architecture test).
- After deploy, KB-016's and run 17's consistency queries stay at zero.

## Open questions

- Should the REST call for one object in class C wait for its job (with a timeout) or always return the job ID?
- Which roles get the raw repair permission at MZK?
- Does the admin client already schedule a reindex after `setMODS` and children order? The endpoints do not; the client was
  not checked.
