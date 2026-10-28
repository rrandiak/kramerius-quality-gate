---
id: BUG-014
former_id: BUG-009
category: bug
title: The process manager marks a job FAILED after one failed status call to its worker, even if the job is still running
area: communication
severity: medium
effort: XS               # GCTask: count consecutive probe failures per job
use_cases: [indexing, ingest, admin]
review_ref: [B8]
upstream: null
checked: [source]
checked_how: "Read GCTask at process-platform da88e6a; not observed"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-014 — The process manager marks a job FAILED after one failed status call to its worker, even if the job is still running

> **In one sentence:** every GC round asks each worker with a RUNNING job for its status, and if that one HTTP call fails for
> any reason (network blip, slow worker, DNS) the job is set to FAILED at once, while it may well be running and later
> finish its work.

## Symptom

A long job (reindex, import) shows **Failed** in the admin UI while it is still working; its log keeps growing on the worker.
Today it usually ends as **Finished** after all, because the late FINISHED report overwrites FAILED
([BUG-021](BUG-021-kill-overwritten-by-late-report.md)). Batches and anyone who reacted to the FAILED state in between see the
wrong state.

## Cause

`process-platform` `main` at `da88e6a`, `process-manager/.../gc/GCTask.java`:

- For each RUNNING job, GC calls `processService.getWorkerInfo(processId)` (line 57), one `GET /manager/info` to the job's worker
  through `WorkerClient`.
- If the call throws, `catch (Exception e)` (lines 65–68) logs "Cannot access worker for the running process" and calls
  `updateState(processId, FAILED)` right away. There is no retry and no memory of earlier rounds.
- `WorkerClient` uses a pooling HTTP client with `RequestConfig.custom().build()`, i.e. no explicit timeouts, so the
  failures that reach this path are connection errors and resets rather than slow answers.

Whether the job is really dead is only known from the worker; a failed call means "unknown", not "dead". When the worker
container dies, its plugin JVM dies with it, so a single failed call is not a reliable signal on its own.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only. Since 2026-10-27 the process manager is traced with a `GCTask.run` span and `WorkerClient.getWorkerInfo` spans
(chart 1.3.2). A `getWorkerInfo` span with an error, followed by a FINISHED report for the same job, confirms a false failure.

## Impact

- Wrong state shown for running jobs; a batch can be reported as failed while its jobs complete.
- **After BUG-021 is fixed, this gets worse:** with guarded state transitions FAILED becomes final, so a job that hit one bad
  probe stays FAILED even though it finished. The two must be fixed together.
- With a shorter GC interval (process-platform#15 suggested 5 s) there are more probes and more chances for a false failure.

## Fix

1. Keep a per-job counter of consecutive failed probes in `GCTask` (or in the scheduler, since tasks are recreated each round).
   Set FAILED only after N failures in a row spanning at least a minimum time (e.g. 3 failures over ≥ 60 s); reset the counter on
   a successful probe.
2. Keep the immediate FAILED when the worker **answers** and says it is idle or runs another PID (line 58–64): that is a real
   signal, not a failed call.
3. Set explicit connect and response timeouts on `WorkerClient`.

The long-term version is lease expiry instead of probing ([QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md)).

## Test

- Unit test: `getWorkerInfo` throws twice, then returns RUNNING with the right PID. The job must stay RUNNING.
- Unit test: `getWorkerInfo` throws on 3 rounds over 60 s. The job becomes FAILED.
- Unit test: the worker answers IDLE. The job becomes FAILED in that round.

## Missing upstream

Not reported (related to process-platform#15, which does not name this path). An issue for
`ceskaexpedice/process-platform` should state:

- **Finding:** `GCTask.run` (`GCTask.java:65–68`) sets a job to FAILED after any exception from `getWorkerInfo`. A failed
  call means "unknown", not "not running": after a short network outage the job keeps running and later reports FINISHED.
- **Fix:** set FAILED only after N consecutive failures (e.g. 3 over at least 60 s); keep failing at once when the worker
  answers that it is idle or runs another PID. Related to conditional state updates: once those exist, a false FAILED would
  become permanent.

## Related

- [KB-001](../known-bugs/KB-001-process-gc-stops-forever.md): the same GC round can also stop GC for good.
- [BUG-021](BUG-021-kill-overwritten-by-late-report.md): fix together; the state guard makes false FAILED permanent.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): lease-based liveness instead of probing.
