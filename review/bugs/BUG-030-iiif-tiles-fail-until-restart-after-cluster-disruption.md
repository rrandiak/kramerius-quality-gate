---
id: BUG-030
former_id: null
category: bug
title: After a cluster disruption, kramerius-public answers 500 for most IIIF tiles until it is restarted, while staying Ready
area: imaging
severity: high
effort: M                # rebuild the shared async client when it stops, log the cause; plus a health check on it
touches: [search, rest]
contracts: []
data_migration: false
use_cases: [image-open]
review_ref: []
upstream: null
checked: [source, production]
checked_how: "Read IiifServlet, AbstractImageServlet and HttpAsyncClientProvider at Kramerius 560676c; MZK NGINX logs and traces 2026-10-29 02:40–08:10Z (52,503 failed tile requests; spans of failing vs working tile traces), 30 days of NGINX tile status"
checked_on: 2026-10-29
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-030 — After a cluster disruption, kramerius-public answers 500 for most IIIF tiles until it is restarted, while staying Ready

> **In one sentence:** after a disruption in the cluster (at MZK, typically a Kubernetes node update), the public pods
> keep running and stay Ready, but most IIIF tile requests fail with 500 within milliseconds, without ever calling the image
> server, while thumbnails, previews and `info.json` keep working; only a manual restart of the pods ends it.

## Symptom

Readers see thumbnails and the page preview, but the zoomable image does not load. NGINX shows 500 on
`/search/iiif/{pid}/{region}/{size}/…` tile requests; `info.json`, `image/thumb` and `image/preview` answer as usual. The
pods are Running and Ready, so Kubernetes does nothing. MZK operators restart kramerius-public by hand, which helps.

## Cause

Kramerius `origin/master` at `560676c`:

- On the non-CDK path, a tile request runs the rights check, reads the object's `tiles-url` from Akubra, then calls
  `copyFromImageServer` (`search/src/java/cz/incad/Kramerius/imaging/IiifServlet.java:157–195`).
- `copyFromImageServer` sends the request through **one shared `HttpAsyncClient`**, a Guice singleton
  (`search/src/java/cz/incad/Kramerius/backend/guice/BaseModule.java:109`), started once at application start by
  `HttpAsyncClientLifeCycleHook` (`rest/src/main/java/cz/incad/kramerius/rest/api/guice/HttpAsyncClientLifeCycleHook.java:26`)
  and never checked or rebuilt afterwards (`search/src/java/cz/incad/Kramerius/AbstractImageServlet.java:251–257`).
- Any failure there ends in the servlet's catch-all, which logs to the Tomcat log and sends a bare 500
  (`IiifServlet.java:208–213`). Nothing is recorded on the trace, no metric counts it, and no health check looks at the client.
- `info.json` on the same path does **not** use this client: it opens a fresh `HttpURLConnection` per request
  (`IiifServlet.java:183–186`). Thumbnails and previews are read from Akubra. That is why they keep working.

The failing requests never reach the image server and fail fast (see below). That fits an async client whose I/O reactor has
stopped: Apache HttpClient 5 then rejects every `execute` at once, and the client stays in that state for the life of the
JVM. A full connection pool would make requests wait for a connection, not fail at once. **The exact exception is not
known yet:** the Tomcat log of the failing period was lost with the restart (see "To confirm").

## Evidence and frequency

MZK production, 2026-10-29 (times in UTC):

| Time | What happened |
| --- | --- |
| 02:10–02:55 | Node update window: Solr refuses connections, process-manager is unreachable, `process-db-1` restarts. |
| **02:50–07:53** | **IIIF tiles fail:** 52,523 tile 500s in NGINX (52,503 failed tile traces), 67–82 % of all tiles per hour, up to 100 % in some 10-minute windows. CDK forward IIIF 100 % 5xx in 05:00–07:00. |
| same window | `info.json`, `image/thumb`, `image/preview` and `image` (full) stay at their usual error rates. |
| 07:50–07:54 | Operators restart `kramerius-db` and then kramerius-public by hand. From 08:00, 0 tile 500s. |

What the failing tile traces contain (all error traces are kept by the trace sampler, so the failing side is complete):

| | Failing tile traces | Working tile traces |
| --- | --- | --- |
| Rights check, incl. its Postgres SELECTs | runs, no error | runs |
| Solr `getPidPaths`, Akubra read, `iiifImageEndpoint` | run, no error (4 Solr 503s at 02:56) | run |
| GET to the image server (`imageserver-proxy`) | **none** | 1 per tile, 200, ~73 ms |
| Root span | 500 via `sendError`, ~73 ms in total, no exception on any span | 200 |

So the database was not the cause: in the failing traces Postgres answered normally. Database errors appear in only 2 traces,
at 07:49–07:53, when `kramerius-db` itself was restarted.

**How often:** MZK operators say it happens often after Kubernetes node updates and that a restart is the known remedy. In
the last 30 days of NGINX logs, only this episode reaches 20 % tile 5xx in an hour; earlier ones were either shorter or
restarted before they show at that threshold. Not every node update triggers it (the node updates on 2026-10-28 did not).

**Open:** whether both public pods were broken or only one. Traces have no pod name, and NGINX still served some tiles with
200 during the window (about 20,000 in 03:00–07:30), which would fit one broken pod and one working one.

### To confirm (next time it happens, before restarting)

Save the Tomcat log of each public pod, without PIDs, and look for the exception behind the 500s, e.g.
`I/O reactor`, `IOReactor`, `Request execution cancelled`, `ExecutionException` or `IllegalStateException` next to
`IiifServlet` or `AbstractImageServlet`. Also check which pod the 500s come from. That shows the real exception and when the
client stopped.

## Impact

High for readers: for about five hours most pages could not be zoomed, on the main image path of the public site and for CDK
users served through the forward endpoint. Nothing alerts on it, because the pods stay Ready and the failure is visible
only in NGINX status codes and in the Tomcat log. Operators find out from users and restart by hand.

## Fix

1. **Don't keep a dead client.** Wrap the shared `HttpAsyncClient` so that, when it is no longer active
   (`CloseableHttpAsyncClient.getStatus()` is not `ACTIVE`) or `execute` fails because the reactor has stopped, it is
   closed and rebuilt, with a log line that names the cause.
2. **Make the failure visible:** record the exception on the tile span and log it once per cause, not as a bare 500.
   Optionally fall back to the same per-request connection `info.json` uses, so a tile still loads while the client is
   rebuilt.
3. **Health check:** let the readiness or liveness probe fail when the image-server client is not active, or when tile
   fetches keep failing. Kubernetes then restarts the pod instead of an operator.

Step 1 is S; with the health check (new configuration in the deployment), M.

## Test

- Unit or integration test: start the servlet with a stub image server, stop the shared client (simulate a stopped
  reactor), request a tile. Before the fix: 500 for every following request. After the fix: the client is rebuilt and the
  next tile loads.
- Staging: restart the node that runs the image server proxy while tiles are requested, and check that tile 500s stop
  without restarting Kramerius.

## Missing upstream

Not reported. A new issue in `kramerius` should state:

- `AbstractImageServlet.copyFromImageServer` (`AbstractImageServlet.java:251–257` at `560676c`) uses one singleton
  `HttpAsyncClient` (`BaseModule.java:109`), started once (`HttpAsyncClientLifeCycleHook.java:26`) and never checked or
  rebuilt.
- After a cluster disruption at MZK (2026-10-29), tile requests failed fast with 500 without calling the image server,
  for 5 hours, until the pods were restarted; `info.json`, which uses a per-request connection, kept working.
- The failure becomes a bare 500 in `IiifServlet.java:208–213`, with no trace or metric.
- Fix: rebuild the client when it is no longer active, log the cause, and expose its state to a health check.

## Related

- [BUG-026](BUG-026-iiif-500-for-objects-without-tiles.md): the same servlet's other bare-500 path.
- [KB-003](../known-bugs/KB-003-cdk-probes-info-json-per-tile.md): the CDK tile path.
- [QOL-001](../quality-of-life/QOL-001-otel-in-images-replace-monitor-core.md): metrics that would have alerted on this.
