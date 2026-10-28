---
id: KB-002
former_id: BUG-006
category: known-bug
title: A worker stops taking jobs for good after one failed poll to the process manager
area: communication
severity: high
effort: XS               # WorkerLoop only
use_cases: [indexing, ingest, admin]
review_ref: [B6]
upstream: "ceskaexpedice/process-platform#13"
checked: [source, production, upstream-report]
checked_how: "Read the worker loop at process-platform da88e6a; MZK worker traces 2026-10-28 (all 10 loops exited); process-platform#13"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-002 — A worker stops taking jobs for good after one failed poll to the process manager

> **In one sentence:** if one request from a worker to the process manager fails (manager restarting, a network blip, any
> HTTP status other than 200 or 404), the worker's polling thread ends, while Tomcat and the pod keep running and look healthy,
> so the worker silently never takes another job until it is restarted.

## Symptom

A scheduled job stays PLANNED and never starts on a worker; restarting the worker's Tomcat fixes it at once
([process-platform#13](https://github.com/ceskaexpedice/process-platform/issues/13)). The worker log shows, once:

```
SEVERE WorkerLoop  Unexpected error in polling loop
  RemoteNodeException: ... (connection refused / Failed to get next scheduled process)
INFO   WorkerLoop  Worker loop exited.
```

The reporter of #13 hit it after a worker started before the process manager; it went away after raising
`WORKER_LOOP_SLEEP_SEC_KEY` from 0.3 to 10 s, which made it less likely but did not remove it. The maintainers proposed adding
retry logic to HTTP calls.

A worker that starts before the process manager can also fail earlier, in registration, before the loop exists at all. That
case is [KB-005](KB-005-worker-never-starts-if-registration-fails.md) and was seen at MZK on 2026-10-27; the #13 report may
be that one, this one, or both.

## Cause

`process-platform` `main` at `da88e6a`, `process-worker/.../worker/WorkerLoop.java`:

- The polling thread runs `while (running)` (line 49). Each iteration calls `managerClient.getNextScheduledProcess()`
  (line 105).
- `ManagerClient.getNextScheduledProcess` (`ManagerClient.java:113–141`) returns `null` on 404 and throws
  `RemoteNodeException` on any other status and on any `IOException` (connection refused, reset, timeout).
- The loop catches it in `catch (Exception e)` (lines 88–91), logs it and calls `stop()`, which sets `running = false`.
  The thread ends with "Worker loop exited." (line 93). Nothing restarts it.
- The thread is a daemon inside Tomcat. Tomcat keeps serving `/manager/info`, so the process manager's GC still sees an alive,
  IDLE worker, and Kubernetes probes still pass.

Retrying HTTP calls would make the failure rarer, but a failure that outlasts the retries still ends the loop. The defect is
`stop()` in the catch block.

## Evidence and frequency

- Reported in production setups ([#13](https://github.com/ceskaexpedice/process-platform/issues/13), June 2026).
- Any restart of the process manager on its own (deploy of a new version, OOM, node drain) hits every worker that polls
  during the restart window. With `WORKER_LOOP_SLEEP_SECS` around 1 s, that is all of them.
- Since 2026-10-27 the worker JVMs send traces (chart 1.3.2). Every poll is a client span from the worker's service
  (`curator-worker-default`, `curator-worker-import`, `public-worker` on MZK). A pod that is up but whose poll spans stop has a
  dead loop:

```sql
SELECT ServiceName, ResourceAttributes['host.name'] AS pod, max(Timestamp) AS last_poll, count() AS sampled_polls
FROM default.otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND SpanKind = 'SPAN_KIND_CLIENT'
  AND ServiceName IN ('curator-worker-default', 'curator-worker-import', 'public-worker')
  AND (SpanAttributes['url.full'] LIKE '%next_process%' OR SpanAttributes['http.url'] LIKE '%next_process%')
GROUP BY ServiceName, pod ORDER BY last_poll
```

Every poll is kept: an idle poll answers 404, and the collector's tail sampler keeps all traces with an HTTP status of 400 or
more. An idle worker polls about every 10 s (279–448 polls per pod in 75 minutes on 2026-10-27). The loop does not poll while
a job runs, so a gap on a pod whose job has ended, or that the manager no longer sees as busy, means the loop has stopped.
On 2026-10-27 no running loop stopped this way; five pods had no loop from the start ([KB-005](KB-005-worker-never-starts-if-registration-fails.md)).

**Seen in production at MZK on 2026-10-28: all ten worker pods stopped, and no job ran for about 9.5 hours.** The process
manager stopped answering during a night of node and pod restarts (it was restarted at 04:59 UTC). Worker Tomcat logs
(`catalina.2026-10-28.log`, times UTC):

| Time (UTC) | Manager | Loops that exited |
| --- | --- | --- |
| 03:24:00–03:24:07 | accepts connections, does not answer: `RemoteNodeException: Read timed out` | all 10 pods within 7 s (`worker-default-0` … `-7`, `worker-import-0`, `worker-public-0`) |
| 04:52:31–04:52:35 | down: `HttpHostConnectException` (connection refused) | `worker-default-1`, `-2`, `-4`, `-5`, which had restarted in between, registered and polled for 10 s to 85 min |
| 04:59:56–05:00:10 | starting | `worker-default-3`, `worker-import-0`, `worker-public-0` restarted with the manager and failed to register ([KB-005](KB-005-worker-never-starts-if-registration-fails.md)) |

After that, seven pods had a dead loop and three had no `/worker` context. All ten were Running and Ready, no plugin JVM was
running, and nothing restarted them. Every pod logged, once:

```
SEVERE [WorkerPollingThread] WorkerLoop.lambda$start$0 Unexpected error in polling loop
    RemoteNodeException: Read timed out
    Caused by: java.net.SocketTimeoutException: Read timed out
INFO   [WorkerPollingThread] WorkerLoop.lambda$start$0 Worker loop exited.
```

So a manager that hangs for one response timeout is enough; it does not have to restart.

## Impact

- A worker that looks healthy takes no jobs. With several workers, jobs still run, only slower, and nobody notices; with one
  worker for a profile (e.g. `worker-import`), those jobs wait until someone restarts it.
- After a restart of the process manager alone, every worker can stop at once.

## Fix

1. In `WorkerLoop`, replace `stop()` in `catch (Exception e)` with: log, sleep with backoff (e.g. from the configured poll
   interval up to 60 s, with jitter), and continue the loop. Keep `stop()` only for shutdown and interruption.
2. Set explicit connect and response timeouts on the `ManagerClient` `RequestConfig` (today `RequestConfig.custom().build()`,
   line 61), so a hung manager cannot block the loop forever either.
3. Optional: expose the loop state (last successful poll time) in `/manager/info` and in a readiness or liveness probe.

## Test

- Unit test: a `ManagerClient` mock that throws `RemoteNodeException` twice and then returns a job. The loop must keep running
  and launch the job.
- Staging: scale the process manager to 0 for 1 minute, then back to 1. Schedule a job. Every worker must pick up jobs again
  without being restarted.

## Missing upstream

[process-platform#13](https://github.com/ceskaexpedice/process-platform/issues/13) reports workers that stop taking jobs
and suggests that it happens when a worker starts before the process manager. Missing there:

- **Cause:** `WorkerLoop.java:88–91` calls `stop()` on any polling exception (`RemoteNodeException` on connection refused
  or on any status other than 200/404), and the polling thread ends ("Worker loop exited."). Tomcat keeps running, so the
  worker looks healthy but never takes a job again. Retries on the HTTP calls only delay this: a longer manager outage (a
  restart during a deploy) still ends the thread.
- **It is not only a startup problem:** at MZK on 2026-10-28 the manager stopped answering at night (`Read timed out`),
  and the polling loops of all 10 workers ended within 7 seconds. The pods stayed Ready, and no job ran for about 9.5
  hours until someone noticed. One polling timeout is enough.
- **Fix:** in the `catch`, log, wait with backoff and continue instead of `stop()`; set timeouts in the `RequestConfig` of
  `ManagerClient` (line 61), which has none.

## Related

- [KB-001](KB-001-process-gc-stops-forever.md): the process manager's GC has the same "stop on first exception" pattern.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): the broader redesign of manager–worker communication.
