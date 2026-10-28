# Curator write boundaries — source-only pass

This pass followed selected curator mutations through Akubra, the processing index, Solr, and process scheduling. It did not execute writes or tests. The checked source has not been matched to the deployed image, so runtime incidence is unknown.

## New source finding

**B20 / high — thumbnail replacement can leave the target object absent.** `ItemsResource.setImgThumb` reads a source thumbnail, then locks the target, builds a complete replacement FOXML, calls `akubraRepository.delete(targetPid, false, false)`, calls `akubraRepository.ingest(updatedDigitalObject)`, and commits (`ItemsResource.java:823–848`). `CoreRepositoryImpl.delete` removes the object and its processing-index description before returning (`CoreRepositoryImpl.java:136–158`); `ingest` writes and rebuilds the processing index (`CoreRepositoryImpl.java:101–113`). The lock is mutual exclusion, not a transaction across those operations. If ingest or processing-index rebuilding fails after deletion, the endpoint throws but has no restore step. The target FOXML can remain absent or its processing-index state can be inconsistent. B9's swallowed storage errors add another failure mode, but this delete/ingest sequence is a distinct hazard.

Later validation in the benchmarking environment: snapshot an isolated target, inject failure immediately after delete and during ingest/rebuild, then compare object bytes, datastream references, processing-index entries, and endpoint outcome. A safer design would replace the FOXML atomically where storage permits, or stage a complete replacement plus explicit recovery/compensation. Define behavior for shared managed datastream references before repair.

## Mutation and visibility map

| Operation | Source sequence | Consistency question for later validation |
| --- | --- | --- |
| Create collection | `CollectionsResource.java:161–167` ingests Akubra object, then schedules index process. | If manager scheduling fails, object exists without a scheduled search update. Detect and reconcile it; decide whether API response should expose partial success. |
| Edit collection metadata | `CollectionsResource.java:393–426` updates MODS and RELS-EXT under a PID lock, then schedules indexing after releasing it. B19 covers unchanged PUT failure. | Failure between either repository write or scheduling can leave different versions across FOXML, processing index, and search. Compare each state after each injected boundary. |
| Add/remove collection items | `CollectionsResource.java:513–535,613–649,876–922,972–998` changes RELS-EXT, then schedules one or more item index jobs and updates `contains_licenses` in FOXML and Solr. | A batch can be partly scheduled after one repository mutation. Check retry idempotency, missing jobs, stale license facets, and reconciliation. The source alone does not establish incident frequency. |
| Direct datastream/MODS update | `ItemsResource.java:726–775,863–883` writes Akubra and returns OK without scheduling search reindexing in these handlers. | Determine whether callers intentionally schedule elsewhere. Measure repository-to-search visibility delay and identify an explicit owner for reindexing before claiming this is a defect. |
| Delete item | `ItemsResource.java:463–486` deletes from Akubra/processing index, then calls direct search-index deletion. | Define behavior if either index update fails; inspect search visibility and retry/reconciliation contract. B9 already covers swallowed Akubra deletion errors. |
| Change rights | `RightsResource.java:107–185,289–367` writes rights and criterion parameters through `RightsManager`. | Trace cache invalidation and cross-pod authorization freshness, especially before adding a rights proxy. B2's cache-key issue remains separate. |

For the benchmarking handoff, record one timeline per mutation: request accepted, repository write, processing-index update, search update or scheduled job, public visibility, and recovery after failure. Use isolated fixtures and compare exact object/index state. These are correctness and freshness measurements; they do not imply numerical throughput or latency gains. No application changes or tests were made in this run.
