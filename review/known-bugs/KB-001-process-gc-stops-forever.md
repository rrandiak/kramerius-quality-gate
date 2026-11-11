---
id: KB-001
former_id: BUG-005
category: known-bug
title: The process manager's GC stops for good after one exception, so dead jobs stay "Running"
area: communication
severity: high
effort: XS               # GCTask and GCScheduler only
use_cases: [indexing, ingest, admin]
review_ref: []           # new; related to B8
upstream: https://github.com/ceskaexpedice/process-platform/issues/15#issuecomment-6804387715
checked: [source, production, upstream-report]
checked_how: "Read GCTask at process-platform da88e6a, v1.5 (4974929, deployed manager) and v1.5.2 (285f1e5); process-manager catalina logs 2026-10-12 to 2026-11-11; GCTask.run spans 2026-10-27 to 2026-11-11; process-db rows of the affected jobs"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-001 — The process manager's GC stops for good after one exception, so dead jobs stay "Running"

> **In one sentence:** the background check that marks jobs of dead workers as FAILED cancels its own timer the first time
> any exception escapes it, and nothing ever starts it again, so after one database hiccup or one deleted job every later
> worker crash leaves its jobs in "Running" until the process manager is restarted.

## Upstream issue

Comment on [process-platform#15](https://github.com/ceskaexpedice/process-platform/issues/15) (opened by MZK on 2026-06-17),
posted on 2026-11-11 ([comment](https://github.com/ceskaexpedice/process-platform/issues/15#issuecomment-6804387715)): the cause (one exception in `GCTask.run` calls `shutdown()`, the next round is only
scheduled after a successful one, so a shorter interval does not help), an excerpt at v1.5.2 (`285f1e5`), the MZK case of
2026-11-05 (log lines, 36 hours without GC, a job 11.5 hours in "Running"), a one-line repro and the fix (schedule the next
round in `finally` without `shutdown()`; give the `updateState` in the per-job `catch` its own `try`).

## Symptom

After a worker pod is restarted or crashes (e.g. during a deploy), its job stays in state **Běží** (RUNNING) indefinitely
([process-platform#15](https://github.com/ceskaexpedice/process-platform/issues/15)). The maintainer's explanation there was
that GC runs every `GC_SCHEDULER_CHECK_INTERVAL` (10 s) and the restart fell between two runs, and the suggested fix was a
shorter interval. That explains a delay of a few seconds, not a job that stays RUNNING for good.

The process manager log contains, once:

```
INFO  GCScheduler  Cancelling gcScheduler
SEVERE GCTask      <message of the exception>
```

and after that no GC activity at all.

## Cause

`process-platform` `main` at `da88e6a` (2026-09-18):

- `GCScheduler` (`manager/gc/GCScheduler.java`) runs GC on one `java.util.Timer`. `init()` is called once at startup
  (`ManagerStartupListener.java:78–79`). Each `GCTask` schedules the **next** run itself, as the last statement of a successful
  run (`GCTask.java:73`). `shutdown()` calls `timer.cancel()`, which is permanent.
- `GCTask.run` (`GCTask.java:31–78`) wraps the whole round in `catch (Throwable e)` and calls `gcScheduler.shutdown()`
  (lines 74–76). So any exception that reaches that level ends GC for the life of the JVM.
- Exceptions that reach it:
  1. `processService.getProcesses(RUNNING)` (line 48) throws `DataAccessException` if the database is unreachable or the
     pool is exhausted for a moment, e.g. while PostgreSQL restarts during the same deploy that restarts the workers.
  2. The per-process `catch (Exception e)` (lines 65–68) calls `processService.updateState(…, FAILED)` without its own
     `try`. If that call fails, the exception leaves the loop. It fails on a database error, and also when the process row no
     longer exists: `ProcessService.updateState` throws `BusinessLogicException(NOT_FOUND)` when the `UPDATE` matches no row.
     So a RUNNING job that an admin deletes while a GC round is in progress is enough: line 53 or 64 throws NOT_FOUND, the
     `catch` calls `updateState` again, it throws NOT_FOUND again, and GC is gone.
  3. Any `Error` (e.g. `OutOfMemoryError`).

## Evidence and frequency

**Seen in production at MZK on 2026-11-05 and 2026-11-06: GC was dead for 36 hours, then once more for one hour.**

The MZK process manager ran process-platform v1.5 (`4974929`, image `ceskaexpedice/process-manager:1.5`) through these
incidents; `GCTask` and `GCScheduler` are the same in v1.5, v1.5.2 (`285f1e5`) and `main` (`da88e6a`). v1.5 leaves the
manager's Hikari pool at its defaults, so a connection wait ends after 30 s: the 30,001 ms of the last round below. The
manager was upgraded to 1.5.2 (configurable pool, still the same `GCTask`) on 2026-11-11 at 19:42 UTC. The process manager's Tomcat log
(`/usr/local/tomcat/logs/catalina.*.log`, kept about 30 days across pod restarts; times UTC):

| Time (UTC) | Event |
| --- | --- |
| 2026-11-05 02:50:36 | last GC round; process-db unreachable (`Cannot get database connection from the pool` on the API threads too); the round waits 30,001 ms for a connection |
| 2026-11-05 02:51:06 | `GCScheduler.shutdown Cancelling gcScheduler`, then `GCTask.run Cannot get database connection from the pool.` |
| 2026-11-05 02:51 – 2026-11-06 14:50 | no GC round; the manager keeps serving requests (9,000–41,000 spans every 3 hours, 0 `GCTask.run`) |
| 2026-11-06 14:50:15 | manager restarted together with the other pods |
| 2026-11-06 14:50:19 | first GC round marks two RUNNING jobs FAILED: `eb655ded…` (below) and `9852d91f…`, which had started at 14:46 on a worker pod restarted since |
| 2026-11-06 14:51:40 | database unreachable again for a moment: `Cancelling gcScheduler` a second time |
| 2026-11-06 15:50:48 | manager restarted again; GC has run since |

So trigger 1 above (`getProcesses` on a database outage) is what happens in practice: the trace of the last round has no
child span (no connection was ever obtained) and no error status, because `catch (Throwable)` swallows the exception.

Cost: job `eb655ded…` (`processing_rebuild_for_object` on `worker-default-2`) started 2026-11-06 03:14 UTC and stayed RUNNING
until the first round after the restart marked it FAILED at 14:50:19, 11.5 hours later. Successful runs of that profile
take 53 s on average and at most 50 minutes (30 days, 9,310 runs), so its JVM had been gone for hours. The same database
outage at 02:50 also ended the polling loop of `worker-default-6`
([KB-002](KB-002-worker-loop-stops-on-poll-error.md)).

Detection since 2026-10-27: the process manager sends a method span on `GCTask.run` (chart 1.3.2,
`observability.otel.processManager.includeMethods`). The collector keeps 1% of them (about 86 a day at a 10 s interval), so
a gap of several hours while other process-manager spans continue means GC is dead. An error status does not show it:

```sql
SELECT toStartOfInterval(Timestamp, INTERVAL 3 HOUR) AS h, countIf(SpanName = 'GCTask.run') AS gc_rounds, count() AS all_spans
FROM default.otel_traces
WHERE ServiceName = 'process-manager' AND Timestamp >= now() - INTERVAL 7 DAY
GROUP BY h ORDER BY h
```

## Impact

- Every job whose worker dies after GC has stopped stays RUNNING forever: wrong state in the admin UI, no FAILED status to
  trigger a retry, and batches that never finish.
- It is silent: there is one log line, and the process manager keeps working otherwise.
- Only a restart of the process manager brings GC back.

## Fix

1. Never let an exception end the schedule. Replace the self-rescheduling `Timer` with
   `ScheduledExecutorService.scheduleWithFixedDelay(gcTask, interval, interval, MILLISECONDS)`, and catch and log `Exception`
   inside `run()` without cancelling anything. (A task that throws stops a `scheduleWithFixedDelay` schedule too, so the catch is
   needed either way.)
2. Make the per-process handling unable to throw: wrap the `updateState(…, FAILED)` in the `catch` block in its own
   `try/catch`, and treat NOT_FOUND as "already gone, skip".
3. Keep `shutdown()` only for application shutdown.

## Test

- Unit test: a `ProcessService` mock whose `getProcesses` throws once, then returns normally. GC must run again on the next
  interval and mark a RUNNING job of an unreachable worker FAILED.
- Unit test: a RUNNING job whose `updateState` throws NOT_FOUND. The round must continue with the next job, and the next round
  must still run.
- Staging: stop PostgreSQL for 30 s while a job runs, start it again, then kill the worker pod. The job must become FAILED
  within one interval.

## Related

- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): replaces probing GC with lease expiry; until then GC must at
  least keep running.
- [BUG-014](../bugs/BUG-014-gc-fails-running-job-on-one-probe-error.md) (GC marks a still-running job FAILED when the worker
  probe fails): the opposite failure of the same `GCTask`.
- [KB-002](KB-002-worker-loop-stops-on-poll-error.md): the worker's poll loop has the same "stop on first exception" pattern.
