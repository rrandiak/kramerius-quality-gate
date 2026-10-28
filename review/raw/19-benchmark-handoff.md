# Benchmarking-environment handoff — workload and evidence contract

This is a handoff for the separate Kramerius benchmarking-environment work. It defines what to measure once that environment exists; it does not add fixtures, execute tests, or assume a performance gain. Source-derived risks and production observations must remain separate. The production image digest is known, but the checked-out source has not been matched to its commit except that B11's relevant deployed exception classes were inspected.

## First two runs

| Run | Fixed input and conditions | Capture | Decision gate |
| --- | --- | --- | --- |
| A. IIIF stage baseline | Representative direct and forwarded `info.json` plus tile requests; same image-server behavior, authorization/path mix, warm and cold states, and offered concurrency across repeats. Include one browser image-opening flow. | End-to-end p50/p95/p99 and successful throughput; timed Solr path lookup, rights decision, access-log enrichment/read/write, Akubra tiles URL, upstream image-server call, transfer; per-event ancestor count/FOXML bytes; Solr/NFS/CPU and log-write errors. Keep direct and forwarded routes separate. | Identify a **measured** critical-path stage. Select one small candidate only if its cost is material and its correctness contract is defined. Existing traces show a logs POST before image-server GET, not how much time that work consumes ([Run 02](02-iiif-logging.md)). |
| B. Fixed PID-list indexing baseline | A versioned manifest with small and large FOXML, shallow/deep parents, OCR, image metadata, PDFs, foster links, update and delete cases; same Solr commit policy and one writer for the first baseline. Run concurrently with fixed IIIF/search load once the idle baseline is stable. | Job duration, documents/s, exact expected-versus-actual index manifest, per-stage Akubra/processing-index/NFS reads and bytes, XML/CPU work, Solr add/commit time, visibility delay, heap, GC, NFS retransmits/latency, interactive p95/p99. | Choose bounded read prefetch **or** Solr batching from observed stage cost. Hold the other dimension fixed for the first comparison ([Run 05](05-read-index-capacity.md)). |

These are the smallest performance pilots. The first run should be instrumentation and baseline, not a change to logging or indexing. Compare identical manifests and load windows; retain absolute and relative results plus run-to-run variation. Do not sum overlapping stage times or extrapolate a whole-service gain from a microbenchmark.

## Correctness and availability scenarios after the environment is ready

| Priority | Scenario | Required observation |
| --- | --- | --- |
| 1 / B15 | Inject one document failure inside a model-wide tree job. | Job status, `Counters.errors`, reported top-level indexed count, `full_indexation_in_progress`, `indexer_version`, missing/partial Solr documents, and behavior of a selective rerun. |
| 1 / B17 | Repeated malformed FOXML reads in an isolated Akubra copy. | Unmarshaller-pool availability and latency of a later valid read, for both storage and direct unmarshal paths. No production object or worker should be used. |
| 1 / B20 | Fail between thumbnail target delete and ingest/rebuild. | Target FOXML bytes and existence, referenced datastream bytes, processing-index entries, endpoint result, and recovery path. |
| 1 / B24 | Fail between Akubra datastream delete and replacement create. | Old/new FOXML and referenced bytes, RELS-EXT processing-index relations where relevant, method result, and retry/recovery outcome. |
| 1 / B26 | Apply different read decisions to two streams of one object under the same user/path. | Public item endpoint authorization versus stream-aware rights decision, for both stream orders and public pods. Confirm active policy relevance before severity escalation. |
| 2 / B10, B21–B23 | Folder add/remove, owner-insert failure, nonempty folder delete, duplicate-ID batch and mid-batch failure against the deployed schema. | `items_count` versus actual count, ownerless/orphan rows, exact committed IDs, endpoint result. Also measure folder-list SQL calls versus folder count to assess the N+1 candidate ([folders audit](18-folders-source-audit.md)). |
| 2 / B6–B8, B16 | Worker poll failure/lost claim, brief manager–worker partition, and worker-log 200/404/500. | Schedule-to-start distribution, job state after recovery, duplicate execution evidence, log proxy status and leased connections. |
| 2 / B25 | Deliver a delayed worker state report after a manager GC or cancellation transition. | Whether a terminal state is overwritten, timestamp consistency, claim identity, and retry eligibility. |

These are later environment requirements, **not tests to add now**. Use sanitized, synthetic or approved copied data. A correctness repair can be justified without a speed gain; measure throughput only if its implementation changes critical-path work.

## Search incident stream, separate from speed trials

Keep healthy search performance and incident diagnosis in separate reports. For the 2026-10-19 production sample, two bounded spikes linked every failing `SearchResource.get` trace to a Solr HTTP 400, and deployed bytecode has the B11 exception mismatch that maps this to API 500 ([correlation](12-search-400-correlation.md)). This does not reveal why Solr rejected the queries or account for every day's 5xx. Obtain sanitized Solr rejection fingerprints, effective schema, and operator incident timeline. In the environment, compare representative query classes for latency, successful throughput, facets/highlighting and relevance while healthy; separately classify upstream 400, 5xx, timeout/connect, and recovery. Do not use a corrected HTTP status as evidence of faster or more successful searches.

## Minimum manifest and telemetry contract

- Pin application, Akubra, process-platform, Solr, image-server, and schema revisions; record effective configuration, topology, CPU/memory budgets, NFS mount and storage behavior, and cache state.
- Version a workload manifest by IDs or hashes kept within the approved environment: IIIF path class and image shape; sanitized search query class/filter/result size; indexing root/model, FOXML/datastream size class, parent depth, OCR/PDF/foster/update characteristics. Keep access tokens, user data, full URLs, and raw PIDs out of shared reports.
- Capture correlation IDs across ingress/application/dependency where possible. NGINX `endpoint` is a **manually curated** classification; classify forwarded IIIF by actual path family. NGINX times are proxy end-to-end times, and OTel error spans are not HTTP error counts ([baseline](01-baseline.md)).
- Define acceptance objectives before comparing variants: image-opening latency and success, index visibility delay and document correctness, search feature/relevance parity and success, log completeness/delay, recovery time, and acceptable public-load interference. Report the objective and tested operating range with each result.

The environment team needs access to representative workload manifests, deployed build/config/schema metadata, safe failure injection, NFS/Solr/JVM/worker metrics, and sanitized Solr incident evidence. If any is missing, report that gap rather than substituting guessed speedups. No production or application source was changed for this handoff.
