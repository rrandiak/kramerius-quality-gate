---
id: QOL-008
former_id: null
category: quality-of-life
title: Give FOXML one parsing layer in Akubra, with shared parser factories and one parsed model that callers project from
area: storage
impact: unknown          # fewer code paths and fewer pool users (BUG-002) for sure; speed gain not measured yet
effort: L                # Akubra read API (contract), callers in Kramerius; shared factories alone are S
touches: [akubra (AkubraDOManager, CoreRepositoryImpl, utils, impl/utils), kramerius (shared:common XMLUtils, rest, processes)]
contracts: [api]
data_migration: false
use_cases: [image-open, indexing, admin, ingest]
review: [15-cross-module-code-audit, 16-akubra-pool-reproduction]
upstream: null
---

# QOL-008 — Give FOXML one parsing layer in Akubra, with shared parser factories and one parsed model that callers project from

> **In one sentence:** FOXML is parsed today by four mechanisms in Akubra and three more in Kramerius, each creating its
> parser factory per call and each caller choosing its own representation, so first measure what that costs, share the
> factories, and then let Akubra parse each object once into one light model that callers take projections from, keeping
> JAXB only for writes.

## Today

Akubra `51d821b`, Kramerius `560676c`. Source reading only; no parsing cost has been measured.

**Akubra parses FOXML in four ways:**

| Mechanism | Where | Used for | Factory |
| --- | --- | --- | --- |
| JAXB `DigitalObject` | `AkubraDOManager.readObjectFromStorage`, `unmarshallObject` (lines 130, 274) | writes, deletes, export, `asDigitalObject()` | one `JAXBContext`, a pool of 50 unmarshallers that leaks on errors ([BUG-002](../bugs/BUG-002-unmarshaller-pool-leaks-on-error.md)) |
| SAX | `RepositoryUtils` (lines 107, 163), `InternalSaxUtils` (38, 57, 69), `RelsExtInternalSaxUtils` (38, 58, 77, 96), `ObjectPropertiesSaxParser` (41) | datastream content and metadata, RELS-EXT, object properties | `SAXParserFactory.newInstance()` **on every call** |
| DOM | `DomUtils.streamToDocument` (lines 65–135), `CoreRepositoryImpl.elementFromInputStream` (line 337) | `asDom()`, inline XML | `DocumentBuilderFactory.newInstance()` on every call |
| dom4j | `Dom4jUtils` (lines 69, 84, 275) | `asDom4j()` | `new SAXReader()` on every call |

**The read API lets each caller choose.** `get(pid)` returns the raw bytes, and the caller picks `asDigitalObject()`,
`asDom()`, `asDom4j()`, `asInputStream()` or `asString()`. In Kramerius main code: dom4j 27 call sites (mostly admin and
plugins), DOM 37 (public, search WAR, `shared:common`), JAXB 3, raw stream 45 (often parsed again by the caller).

**Kramerius has its own parsers on top:** 25 `DocumentBuilderFactory.newInstance()`, 16 `XPathFactory.newInstance()`,
19 `TransformerFactory.newInstance()`, 11 `JAXBContext.newInstance()`. Only 3 static fields in the whole code base hold a
`DocumentBuilderFactory`, `SAXParserFactory`, `XPathFactory` or `JAXBContext`; the rest are created per call (e.g.
`XMLUtils.java:54`, `:70`, `:86`).

**The same object is parsed more than once, in different ways:**

- Setting a thumbnail (`rest/.../admin/v70/ItemsResource.java:824–846`): the source object is parsed with JAXB, marshalled,
  and parsed again with dom4j; the target is parsed with dom4j, serialized to a string, parsed with JAXB, then deleted and
  ingested (that last part is [BUG-001](../bugs/BUG-001-thumbnail-replace-deletes-object.md)).
- Reading a datastream's metadata and then its content (`AkubraRepositoryImpl.java:226–253`) fetches the FOXML bytes twice
  (`CoreRepositoryImpl.getAsBytes`) and scans them with SAX twice.
- Indexing a page reads FOXML about four times, one of them a full DOM parse
  ([PM-001](../perf-medium/PM-001-read-once-then-prefetch.md)); an IIIF request reads the leaf object twice
  ([PH-001](../perf-hard/PH-001-cache-by-invalidation-need.md), A3), and the access log parses each ancestor as DOM
  ([PM-003](../perf-medium/PM-003-batched-access-log-writer.md)).

## Questions and answers

### Q1. Is this not the same as PM-001 and PH-001?

**Answer:** no. PM-001 and PH-001 decide **how often** an object is read in one unit of work. This entry decides **how** it
is parsed and what callers get. The two meet in one place: once an object is parsed into one model, the read-once holder
of PM-001 and PH-001 A3 holds that model.

### Q2. Quality of life or performance?

| Option | For | Against |
| --- | --- | --- |
| Performance (`PM`) | parsing and factory lookups cost CPU on every request | not measured; the cost may be small next to NFS reads |
| **Quality of life, with a measurement step** | the certain gain is fewer code paths and fewer pool users | — |

**Answer:** quality of life. If step 1 below shows a real cost, step 2 is split off as a `PS` entry with the numbers.

### Q3. What is the one parsed model?

| Option | For | Against |
| --- | --- | --- |
| JAXB `DigitalObject` for everything | exists | full binding of every datastream, including inline XML; the pool of BUG-002 on every read |
| DOM or dom4j for everything | callers know it | full tree for a lookup of one datastream; two libraries today |
| **A light FOXML model** built in one SAX pass: object properties, a datastream index (ID, control group, versions, MIME type, location or inline offsets), RELS-EXT relations | one pass, small, immutable, cacheable per unit of work | new API; callers must migrate |

**Answer:** the light model, with inline XML (MODS, DC, RELS-EXT) parsed on demand into the representation the caller asks
for. JAXB stays for writes, where the object is rebuilt anyway.

### Q4. Are shared factories safe?

**Answer:** yes, if configured once and used only to create parsers: `DocumentBuilderFactory`, `SAXParserFactory` and
`XPathFactory` are not guaranteed thread-safe, so keep one configured factory per class and a parser per thread
(`ThreadLocal`), or create the parser from a factory held per thread. JAXB `Unmarshaller` per thread replaces the pool
(the BUG-002 fix already suggests a `ThreadLocal<Unmarshaller>`).

## Proposal

| Step | What changes | Effort | Needs |
| --- | --- | --- | --- |
| 1. Measure | a JMH benchmark of factory creation plus parse per mechanism on a page, a monograph and a 3,000-member parent FOXML; and from traces, the share of `info.json`, item info and indexing time spent parsing | S | nothing |
| 2. Shared factories | one configured factory per kind, parsers per thread, in Akubra's utils and Kramerius's `XMLUtils`; `ThreadLocal<Unmarshaller>` instead of the pool | S | step 1 decides whether it is worth a `PS` entry |
| 3. One parsed model | `FoxmlModel` from one SAX pass; `get(pid)` can return it; datastream metadata, content lookup, RELS-EXT and stream names come from it | M | step 2 |
| 4. Callers move | hot paths first (IIIF, item info, rights, access log), then curator handlers and plugins; `asDom` / `asDom4j` on the whole object deprecated | L | step 3; [QOL-002.1](QOL-002.1-narrow-interfaces.md)'s `RepositoryReader` is the natural place |

## What gets easier

| Who | Today | After | Basis |
| --- | --- | --- | --- |
| developers | four Akubra parse paths and three Kramerius ones to keep correct (namespaces, entity settings, encodings) | one parser for reads, JAXB for writes | source |
| operators | a malformed FOXML costs an unmarshaller on any path that uses JAXB | reads no longer touch JAXB; the pool is gone | source, BUG-002 |
| reviewers | XML parser settings (e.g. external entities) differ per call site | set once per factory | source |
| readers of the site | an unknown amount of parse and factory-lookup CPU per request | measured in step 1; reduced if it matters | not measured |

## Costs and risks

- Akubra API change: callers must migrate, and old methods must stay until they do.
- A light model must stay in step with what FOXML can contain (versions, archived streams).
- The gain may be small; step 1 can show that only steps 2 and 3 are worth it.

## Alternatives

1. **Do nothing.** Parsing stays spread over seven mechanisms; BUG-002 is fixed alone.
2. **Only shared factories (step 2).** Cheap; keeps the many representations.
3. **JAXB everywhere.** One model, but the heaviest one, on every read.

## Effort

**Size: L**, set by an Akubra API change with callers in several modules.

| Part | Size | Why this size |
| --- | --- | --- |
| Benchmark and trace check | S | JMH, one ClickHouse query |
| Shared factories, per-thread parsers and unmarshallers | S | utility classes in two repositories |
| Light FOXML model in Akubra | M | new component, one SAX pass, tests against real FOXML |
| Callers migrated | L | rest, search WAR, plugins |

## How we know it worked

- Step 1 produces numbers per mechanism and per route; if parsing is under a few percent of request time, stop after
  step 2.
- After step 3, a read of a malformed FOXML fails without touching any pool, and `grep` finds no
  `*Factory.newInstance()` outside the shared holders.
- The thumbnail handler and indexing parse each object once (a counter or span per parse in tests).

## Open questions

- Should the model also carry inline datastream bytes, or only offsets into the FOXML?
- Does the CDK or any other library call `asDom()` / `asDom4j()` through Akubra directly?
