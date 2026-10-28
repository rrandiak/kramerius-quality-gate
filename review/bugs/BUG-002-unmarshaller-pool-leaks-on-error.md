---
id: BUG-002
former_id: BUG-018
category: bug
title: Each FOXML that fails to parse removes one unmarshaller from Akubra's pool of 50, and when the pool is empty every write and export in that JVM hangs
area: storage
severity: high
effort: XS               # return the unmarshaller in a finally block
use_cases: [admin, indexing, ingest, storage]
review_ref: [B17]
upstream: null
checked: [source, production]
checked_how: "Read AkubraDOManager pool and its callers at Akubra 51d821b and Kramerius 560676c; 7-day MZK log sweep found no unmarshal errors; 5 malformed FOXML counted; unit test written, not run"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-002 — Each FOXML that fails to parse removes one unmarshaller from Akubra's pool of 50, and when the pool is empty every write and export in that JVM hangs

> **In one sentence:** Akubra borrows a JAXB unmarshaller from a pool of 50 whenever it parses a whole object (every write,
> export and a few reads) and gives it back only when parsing succeeds, so every failed parse permanently shrinks the pool,
> and after 50 failures in one JVM every write and export blocks forever, while ordinary reads (images, IIIF, metadata) keep
> working.

## Symptom

A curator pod, worker or plugin JVM stops making progress on anything that reads a whole object (updates, deletes, exports,
licence and indexing jobs): threads wait in `LinkedBlockingQueue.take()` inside `AkubraDOManager`, with no error. Before that,
the log shows up to 50 `Could not unmarshall object` or `RepositoryException` errors for unreadable FOXML. A restart fixes it.

## Cause

Akubra `51d821b`, `core/repository/impl/AkubraDOManager.java`:

- The pool is a `LinkedBlockingQueue<Unmarshaller>` of capacity 50 (`UNMARSHALLER_POOL_CAPACITY`, line 61; filled at line 86).
- `readObjectFromStorage` (lines 130–143) and `unmarshallObject` (lines 274–284) call `unmarshallerPool.take()`, then
  `unmarshal(...)`, then `unmarshallerPool.offer(unmarshaller)`. If `unmarshal` throws (malformed FOXML, an I/O error while the
  file is streamed from NFS), the exception skips the `offer`, and the unmarshaller is lost.
- `take()` waits without a timeout, so once all 50 are lost, the next caller blocks for good.
- These two methods back `getAsRepositoryObject` (`CoreRepositoryImpl.java:117`), `unmarshall` (`:175`), and
  `deleteObject` and `deleteStream` (`AkubraDOManager.java:175`, `:191`): every datastream create, update and delete
  (`AkubraRepositoryImpl.java:121–200`), and `export` (`:73`).
- **Ordinary reads do not use the pool.** `get(pid)` returns the raw bytes (`AkubraRepositoryImpl.java:64–70`), and
  `getDatastreamContent` / `getDatastreamMetadata` parse those bytes with SAX (`AkubraRepositoryImpl.java:226–253`,
  `CoreRepositoryImpl.getDatastreamContent`). Image, IIIF, thumbnail, OCR, MODS and RELS-EXT reads go this way: they keep
  working on an empty pool, and reading a malformed object this way fails in the SAX parser without losing an unmarshaller.
- **Reads that do use it** (they call `asDigitalObject()` or `getAsRepositoryObject`):
  - the client API's audio routes, through `CachingFedoraUrlManager.getExternalStreamURL`
    (Kramerius `560676c`, `shared/common/.../audio/urlMapping/CachingFedoraUrlManager.java:158`; routes in
    `rest/.../apiNew/client/v70/ItemsResource.java:1266–1486`). A failed lookup is not cached, so every audio request for
    an object with malformed FOXML costs one unmarshaller in that public pod. Not checked: whether the routes reach this
    lookup for any model or only for audio objects, and whether before or after the rights check;
  - processing-index relation rebuilds, which read the target's stream names (`ProcessingIndexSolr.java:382`, `:620`),
    during RELS-EXT writes and indexing.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only; the 7-day log sweep of 2026-10-28 shows no unmarshal errors, so it has not happened at MZK recently. The
preconditions exist: MZK has objects whose FOXML is not well-formed, and more can arise (e.g. from writes
outside Akubra). Any write to them, an export, a processing-index rebuild that reads them, or an audio URL lookup on them
costs one unmarshaller per attempt.
Viewing them (thumbnail, IIIF, metadata) does not: those reads fail in the SAX parser. A job that retries or iterates over
them 50 times in one JVM would hang it.

## Impact

- A whole JVM's repository writes and exports hang until restart, without an error: curator API calls time out, jobs stay
  RUNNING with no progress. Image, IIIF and metadata reads keep working.
- In a public pod, the audio routes are a pool user that anonymous requests reach: once the pool is drained, each later
  audio request blocks for good and holds its Tomcat thread, until the pod restarts.
- Long-lived JVMs (curator, public) accumulate the loss over their lifetime; plugin JVMs per job are less exposed.

## Fix

Return the unmarshaller in a `finally` block in both methods (or use a `ThreadLocal<Unmarshaller>`), and use `poll` with a
timeout instead of `take` so that a drained pool fails loudly instead of hanging. Also cache a failed audio URL lookup in
`CachingFedoraUrlManager`, and repair malformed FOXML when it is found.

## Test

`AkubraDOManagerPoolTest`, a unit test in package `org.ceskaexpedice.akubra.core.repository.impl` (it needs only the
read-only fixture repository in `src/test/resources/data`, no processing index or Hazelcast):

1. Build an `AkubraDOManager` on the fixture object store.
2. Call `unmarshallObject` 60 times (more than the pool's 50) with truncated FOXML held in memory; each call must throw
   `RepositoryException`.
3. Read the fixture monograph with `readObjectFromStorage` under `assertTimeoutPreemptively` (10 s).

Before the fix, step 3 blocks in `unmarshallerPool.take()` and fails on the timeout. After the fix (`offer` in `finally`
in both methods), it returns the object. No stored object is modified.

## Related

- [BUG-007](BUG-007-akubra-swallows-storage-errors.md): other error handling in the same class.
