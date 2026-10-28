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
upstream: "ceskaexpedice/process-platform#15"
checked: [source]
checked_how: "Read GCTask at process-platform da88e6a; not observed (no telemetry before 2026-10-27)"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# KB-001 — The process manager's GC stops for good after one exception, so dead jobs stay "Running"

> **In one sentence:** the background check that marks jobs of dead workers as FAILED cancels its own timer the first time
> any exception escapes it, and nothing ever starts it again, so after one database hiccup or one deleted job every later
> worker crash leaves its jobs in "Running" until the process manager is restarted.

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

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only. Not yet observed directly: the process manager had no telemetry before 2026-10-27, and its container log does not
survive a pod replacement.

Since 2026-10-27 21:17 UTC the process manager sends traces with a method span on `GCTask.run` (chart 1.3.2,
`observability.otel.processManager.includeMethods`). A running GC produces one `GCTask.run` span per interval; if the spans stop
while the process manager keeps serving requests, GC has died:

```sql
SELECT toStartOfHour(Timestamp) AS hour, countIf(SpanName = 'GCTask.run') AS gc_rounds, count() AS all_spans
FROM default.otel_traces
WHERE ServiceName = 'process-manager' AND Timestamp >= now() - INTERVAL 7 DAY
GROUP BY hour ORDER BY hour
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

## Missing upstream

[process-platform#15](https://github.com/ceskaexpedice/process-platform/issues/15) reports jobs stuck as running after a
worker restart. It does not name a cause. Missing there:

- **Cause:** `GCTask.run` (`GCTask.java:74–76`) calls `gcScheduler.shutdown()` on any exception, which cancels the
  `Timer` for good, and the next run is scheduled only at the end of a successful run (line 73). One exception stops the GC
  until the process manager restarts. Possible triggers: a database outage in `getProcesses` (line 48), or the unguarded
  `updateState` in the `catch` block (lines 65–68), which also throws `BusinessLogicException(NOT_FOUND)` when the job was
  deleted in the meantime.
- **Fix:** `scheduleWithFixedDelay`, and in `run()` only log the exception, without `shutdown()`; wrap the `updateState`
  in the `catch` block in its own `try`. A shorter interval does not help.

## Related

- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): replaces probing GC with lease expiry; until then GC must at
  least keep running.
- Review B8 (GC marks a still-running job FAILED when the worker probe fails): the opposite failure of the same `GCTask`.
- [KB-002](KB-002-worker-loop-stops-on-poll-error.md): the worker's poll loop has the same "stop on first exception" pattern.
