---
id: KB-005
former_id: BUG-013
category: known-bug
title: A worker that cannot register with the process manager at startup never takes a job, while its pod looks healthy
area: communication
severity: high
effort: S                # WorkerMain startup: retry registration off the Tomcat startup thread; plus a probe in the chart
use_cases: [indexing, ingest, admin]
review_ref: []
upstream: https://github.com/ceskaexpedice/process-platform/issues/13#issuecomment-6801289041
checked: [source, production, upstream-report]
checked_how: "Read worker registration at process-platform da88e6a; MZK traces 2026-10-27 (5 of 10 pods) and 2026-10-28 (3 of 10); worker catalina logs and process-manager access logs 2026-11-06 to 2026-11-11 (4 of 11)"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-005 — A worker that cannot register with the process manager at startup never takes a job, while its pod looks healthy

> **In one sentence:** a worker registers with the process manager exactly once, while Tomcat starts its webapp; if the
> manager is not reachable at that moment (it starts at the same time after a deploy), the webapp fails to start, the polling
> loop is never created, and the pod keeps running and takes no jobs until someone restarts it.

## Upstream issue

Comment on [process-platform#13](https://github.com/ceskaexpedice/process-platform/issues/13), posted by MZK on
2026-11-11 for KB-002 and KB-005 together ([comment](https://github.com/ceskaexpedice/process-platform/issues/13#issuecomment-6801289041)): both places in the worker (registration once at Tomcat
startup, `stop()` on any polling exception) with excerpts at v1.5.2 (`285f1e5`), why the v1.5.2 timeouts and HTTP
retries do not fix it, the MZK incidents of 2026-10-27 and 2026-10-28, a one-line repro and the fix (register in the
polling thread with backoff; log, back off and continue instead of `stop()`).

## Symptom

Jobs for a profile stay PLANNED. The worker's Tomcat log shows, once, at startup:

```
SEVERE [main] org.apache.catalina.core.StandardContext.startInternal One or more listeners failed to start. ...
SEVERE [main] org.apache.catalina.core.StandardContext.startInternal Context [/worker] startup failed due to previous errors
```

The process manager receives no polls from that worker. Restarting the worker pod fixes it at once.

## Cause

Deployed at MZK (checked 2026-11-11): the **workers** run process-platform **v1.5.2** (`285f1e5`, branch `hotfix/1.5.x`,
bundled in the Kramerius 7.2.2.4 worker images since 2026-10-08), the **process manager** ran **v1.5** (`4974929`, image
`ceskaexpedice/process-manager:1.5`, `process-common-1.5.jar`) through every incident below; it was upgraded to 1.5.2 on
2026-11-11 at 19:42 UTC. `GCTask`, `GCScheduler`, `WorkerLoop` and the worker registration are the same in v1.5, v1.5.2 and
`main` (`da88e6a`, which v1.5.2 is not merged into). v1.5.2 adds the "Issue #13" HTTP client timeouts (`aea65db` worker side,
`e46ca54` manager side) and a configurable manager DB pool.

`process-platform` `main` at `da88e6a`, module `process-worker`:

- `WorkerStartupListener.contextInitialized` calls `new WorkerMain().initialize(config)` on Tomcat's startup thread
  (`config/WorkerStartupListener.java:59–60`).
- `WorkerMain.initialize` calls `registerNode(...)`, then `registerPlugins(...)`, and only then creates and starts the
  `WorkerLoop` (`WorkerMain.java:57–60`).
- `ManagerClient.registerNode` sends one POST to `worker/register_node` and throws `RemoteNodeException` on any non-200/204
  status or any `IOException` (`client/ManagerClient.java:71–88`; `:95–112` in v1.5.2). There is no retry. At `main` its
  `RequestConfig` sets no timeouts; v1.5.2 sets a 10 s connect timeout by default, which matches the ~10.2 s
  `SocketTimeoutException` below.
- The exception leaves `contextInitialized`, so Tomcat marks the `/worker` context as failed. The JVM and the pod stay up.
  No polling thread exists, so nothing retries later.

This is a different code path from [KB-002](KB-002-worker-loop-stops-on-poll-error.md), where a loop that was running exits
on a poll error. Fixing KB-002 does not fix this one.

## Evidence and frequency

**Seen in production at MZK on 2026-10-27.** The process manager and all ten worker pods were restarted together for the
chart 1.3.2 rollout. Read-only trace aggregates from ClickHouse (`default.otel_traces`, 21:18–22:34 UTC):

| Pod | `register_node` at startup | Polls afterwards |
| --- | --- | --- |
| `worker-default-0` … `-3` | no failed attempt traced | 279–448 each, about one per 10 s, until the end of the window |
| `worker-default-4` | no failed attempt traced | 139, until it took a job at 21:43 (status calls from the manager continued) |
| `worker-default-5`, `-6` | `SocketTimeoutException` after ~10.2 s | **none** |
| `worker-default-7` | `HttpHostConnectException` after 76 ms | **none** |
| `worker-import-0` (only import worker) | `SocketTimeoutException` after ~10.2 s | **none** |
| `worker-public-0` (only public worker) | `SocketTimeoutException` after ~10.2 s | **none** |

The failed attempts were at 21:18:24–21:18:51; the manager's first span is at 21:19:02, and four registrations succeeded at
21:19:03. So 5 of 10 worker pods were dead for over an hour, including the only worker for import jobs and the only worker for
public jobs (PDF, e-book and text generation). The Tomcat log of `worker-import-0` showed the two `SEVERE` lines above
(22:18:58 local time). Deleting the five pods fixed it.

Every poll is kept by the collector (an idle poll answers 404, and the tail sampler keeps all traces with an HTTP status of 400
or more), so a pod with no poll spans since its start is reliably a pod with no loop:

```sql
SELECT ServiceName, ResourceAttributes['host.name'] AS pod,
       countIf(SpanName = 'POST' AND StatusCode = 'STATUS_CODE_ERROR') AS failed_register,
       countIf(SpanName = 'GET' AND SpanAttributes['url.full'] LIKE '%next_process%') AS polls,
       max(Timestamp) AS last_span
FROM default.otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND SpanKind = 'SPAN_KIND_CLIENT'
  AND ServiceName IN ('curator-worker-default', 'curator-worker-import', 'public-worker')
GROUP BY ServiceName, pod ORDER BY polls
```

Any deploy that restarts the manager and the workers together can hit it. How many pods fail depends on who wins the start race.

**Seen again on 2026-10-28.** The process manager restarted at 04:59 UTC, after a night of node and pod restarts.
`worker-default-3`, `worker-import-0` and `worker-public-0` started in the same second. Each logged `Registering node at
.../worker/register_node` at 04:59:58–59, then `Context [/worker] startup failed due to previous errors` about 10 s later
(05:00:09–10 UTC; the registration timed out). Again this included the only import worker and the only public worker.
The other seven pods had already lost their polling loop to [KB-002](KB-002-worker-loop-stops-on-poll-error.md), so no
worker took a job from about 03:24 UTC until the pods were restarted.

**Seen again on 2026-11-06.** During pod restarts at 14:49–14:55 UTC, `worker-default-2`, `worker-import-0`,
`worker-public-0` and `worker-external-refs-0` logged `Context [/worker] startup failed due to previous errors`
(`catalina.2026-11-06.log`) and never polled again (process-manager access logs to 2026-11-11). Three of them were the only
worker of their profile, so MZK had no import, public or external-refs worker for five days, until the workers were
restarted by hand on 2026-11-11 (16:26 UTC; all restarted pods registered and polled again within two minutes).

## Impact

- Jobs for a profile served by one worker (import, public) wait indefinitely. With several workers per profile, jobs run more
  slowly and nobody notices.
- Neither the pod nor the manager's node list shows a problem: the MZK worker pods have no liveness or readiness probe (chart
  `livenessProbe: {}` and `readinessProbe: {}` by default), and Kubernetes sees a running Tomcat.

## Fix

1. In `WorkerMain.initialize`, do not let a failed registration end startup. Run registration (node and plugins) in the
   polling thread before the first poll, retrying with backoff and jitter (e.g. from 1 s up to 60 s) until it succeeds, then
   start polling. Tomcat's startup thread is then never blocked or failed by the manager's availability.
2. Explicit timeouts on `ManagerClient`: done in v1.5.2 (`aea65db`).
3. Re-register when a poll shows the manager does not know the node (for example after the manager's DB was reset), so the
   same path also covers a manager that restarted later.
4. In the chart, give worker pods a probe on an endpoint that fails while the `/worker` context is not running (any
   `/worker/api/...` URL returns 404 then). A liveness probe would have restarted the five pods within minutes. Exposing
   "registered and last poll at" in `/worker/api/manager/info` would make the probe exact.

## Test

- Unit test: a `ManagerClient` mock whose `registerNode` throws twice and then succeeds. `initialize` must return normally,
  and the loop must register and then poll.
- Staging: scale the process manager to 0, restart a worker, wait 2 minutes, scale the manager back to 1. The worker must
  register and take a scheduled job without being restarted.

## Related

- [KB-002](KB-002-worker-loop-stops-on-poll-error.md): the running loop exits on one poll error; same symptom, different code.
- [KB-001](KB-001-process-gc-stops-forever.md): the same "fail once, stop for good" pattern in the manager's GC.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): a heartbeat lease would make an unregistered or silent
  worker visible to the manager.
