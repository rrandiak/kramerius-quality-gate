---
id: BUG-012
former_id: BUG-001
category: bug
title: Access log crashes and writes partial records when an ancestor has no Dublin Core
area: async
severity: medium
effort: XS               # two return statements in one class, plus one unit test
use_cases: [image-open]
review_ref: [B13]
upstream: null
checked: [source, production]
checked_how: "Read the access-log code at Kramerius 560676c; MZK OTel spans 2026-10-27 and warm 2026-10-28, weighted for sampling"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-012 — Access log crashes and writes partial records when an ancestor has no Dublin Core

> **In one sentence:** in about 4 of 10 IIIF `info.json` requests (more than half in a short cold sample), the statistics logger throws a `NullPointerException` partway through enrichment and still sends the incomplete record to the Solr `logs` core.

## Symptom

Repeated on stderr of `kramerius-public`:

```text
java.lang.NullPointerException: Cannot read the array length because "<local37>" is null
    at cz.incad.kramerius.statistics.accesslogs.solr.SolrStatisticsAccessLogImpl.reportAccess(SolrStatisticsAccessLogImpl.java:243)
    at cz.incad.kramerius.statistics.accesslogs.AggregatedAccessLogs.reportAccess(AggregatedAccessLogs.java:27)
    at cz.incad.Kramerius.imaging.IiifServlet.reportAccess(IiifServlet.java:229)
    ...
```

The image request still succeeds, because `AggregatedAccessLogs` catches the exception and only prints it.

## Cause

Kramerius `master` at `560676c`, unchanged as of 2026-10-27:

- `LogFields.getDCCreators()` and `getDCPublishers()` return `null` when the object has no DC stream.
- `SolrStatisticsAccessLogImpl.java:242–248` loops over both results without a null check:

```java
String[] creatorsFromDC = logFields.getDCCreators();
for (String cr : creatorsFromDC) {          // line 243, NPE
```

- The `finally` block at line 281 still builds and sends the log record, so the record that reaches Solr
  holds only what was collected before the crash.

## Evidence and frequency

OTel method spans, `kramerius-public`, 2026-10-27 from 15:10 for about 3.5 minutes:
**108 of 193** `SolrStatisticsAccessLogImpl.reportAccess` spans (56%) ended with this exception.
`LogRecord.toSolrBatch` ran 386 times (2 × 193), which confirms that records were sent for failed requests too.

Warm re-measurement, 2026-10-28 06:00 UTC to about 13:30 UTC, `kramerius-public`, counted per trace and weighted for tail
sampling (a trace with an error or ≥ 1 s has weight 1, the rest 100). Failed traces are all kept, so the failure counts are
exact. Counted per trace because `IiifServlet.reportAccess` and `SolrStatisticsAccessLogImpl.reportAccess` are nested
spans that both match, and only the inner one fails:

| Route | Failed requests | Requests with access logging (estimate) | Failed share |
| --- | --- | --- | --- |
| IIIF `info.json` | 23,062 | ≤ 63k from traces; 57k in NGINX for the same window | **~37–40%** |
| all routes (info.json, Zoomify, CDK forward, other) | 25,231 | — | — |

All 25,231 failures are `java.lang.NullPointerException`. That is about 3,400 failed access records an hour in daytime.

## Impact

- **Statistics data:** about 4 in 10 image-open records may be missing authors, publishers,
  identifiers and details for the remaining ancestors. Reports built from the `logs` core undercount these fields.
- **Latency:** none directly. The crash actually makes the logging stage finish sooner.
- **Noise:** a full stack trace on stderr for each affected request.

## Fix

Return `new String[0]` instead of `null` from `LogFields.getDCCreators()` and `getDCPublishers()`.
`AggregatedAccessLogs` should also log through `java.util.logging` instead of `printStackTrace`.

## Test

Add a `LogFieldsTest` case with FOXML that has no `DC` datastream. Assert empty arrays, and assert that
`reportAccess` produces a complete record for a path whose ancestor has no DC.

## Related

- [PM-003](../perf-medium/PM-003-batched-access-log-writer.md): the async logger would rewrite this code path.
  Ship this fix first, separately.
- Open question: which models lack DC? A share this stable (37–56%) suggests a whole model rather than individual objects.
