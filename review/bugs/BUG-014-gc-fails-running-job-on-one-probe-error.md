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
upstream: https://github.com/ceskaexpedice/kramerius/issues/1380
checked: [source, production]
checked_how: "Read GCTask at process-platform da88e6a, v1.5 (4974929, deployed manager) and v1.5.2 (285f1e5); process-manager catalina logs 2026-10-12 to 2026-11-11 (all GC failures), access logs and process-db rows of those jobs; getWorkerInfo spans 2026-10-27 to 2026-11-11"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-014 — The process manager marks a job FAILED after one failed status call to its worker, even if the job is still running

> **In one sentence:** every GC round asks each worker with a RUNNING job for its status, and if that one HTTP call fails for
> any reason (network blip, slow worker, DNS) the job is set to FAILED at once, while it may well be running and later
> finish its work.

## Upstream issue

[kramerius#1380](https://github.com/ceskaexpedice/kramerius/issues/1380) "Bežiaci proces sa označí ako FAILED, keď GC raz
nezastihne jeho workera", opened by MZK on 2026-11-11 from this entry (filed in kramerius like #1375, the code is in
process-platform): cause (any exception from the worker call sets FAILED at once), the excerpt at v1.5.2 (`285f1e5`), the
2026-10-23 timeline, 3 such errors in 30 days of which one false, since when (`b330117`, `v1.0`) and the fix (FAILED only
after the worker has been unreachable for at least 60 s; keep failing at once when the worker answers that it runs nothing).

## Symptom

A long job (reindex, import) shows **Failed** in the admin UI while it is still working; its log keeps growing on the worker.
Today it usually ends as **Finished** after all, because the late FINISHED report overwrites FAILED
([BUG-021](BUG-021-kill-overwritten-by-late-report.md)). Batches and anyone who reacted to the FAILED state in between see the
wrong state.

## Cause

Deployed at MZK (checked 2026-11-11): the **workers** run process-platform **v1.5.2** (`285f1e5`, branch `hotfix/1.5.x`,
bundled in the Kramerius 7.2.2.4 worker images since 2026-10-08), the **process manager** ran **v1.5** (`4974929`, image
`ceskaexpedice/process-manager:1.5`, `process-common-1.5.jar`) through every incident below; it was upgraded to 1.5.2 on
2026-11-11 at 19:42 UTC. `GCTask`, `GCScheduler`, `WorkerLoop` and the worker registration are the same in v1.5, v1.5.2 and
`main` (`da88e6a`, which v1.5.2 is not merged into). v1.5.2 adds the "Issue #13" HTTP client timeouts (`aea65db` worker side,
`e46ca54` manager side) and a configurable manager DB pool.

`process-platform` `main` at `da88e6a`, `process-manager/.../gc/GCTask.java`:

- For each RUNNING job, GC calls `processService.getWorkerInfo(processId)` (line 57), one `GET /manager/info` to the job's worker
  through `WorkerClient`.
- If the call throws, `catch (Exception e)` (lines 65–68) logs "Cannot access worker for the running process" and calls
  `updateState(processId, FAILED)` right away. There is no retry and no memory of earlier rounds.
- At `main`, `WorkerClient` uses a pooling HTTP client with `RequestConfig.custom().build()`, i.e. no explicit timeouts.
  v1.5.2 adds configurable timeouts (`e46ca54`), so a slow worker answer also reaches this path as a failed call. The MZK
  manager ran v1.5 without them, so at MZK only connection and DNS errors took this path so far.

Whether the job is really dead is only known from the worker; a failed call means "unknown", not "dead". When the worker
container dies, its plugin JVM dies with it, so a single failed call is not a reliable signal on its own.

## Evidence and frequency

**Seen in production at MZK on 2026-10-23: one false failure in 30 days.**

The process manager's Tomcat log (`catalina.*.log`, 2026-10-12 to 2026-11-11) has three `Cannot access worker for the
running process` lines (this path) and four `Process' worker idle or not running the process` (a real answer from the
worker). Checked against the manager's access log (the job's own state reports) and `pcp_process`:

| Time (UTC) | Job | Worker call | Afterwards | Verdict |
| --- | --- | --- | --- | --- |
| 2026-10-23 08:17:34 | `ab14951c…` (`add_license`) | `RemoteNodeException: worker-default-4.worker-default…svc.cluster.local` (name did not resolve) | job reported `state=FINISHED` at 08:18:12, final status FINISHED | **false failure** |
| 2026-11-04 09:17:48 | `6c21d98d…` (`remove_license`) | `UnknownHostException: worker-default-0…` | no report; the worker polled from a new pod IP at 09:18:23 | real (pod replaced) |
| 2026-11-05 02:13:46 | `62a9e898…` (`external-refs`) | `HttpHostConnectException` (connection refused) to `worker-external-refs-5` | no report; the worker's last poll from that pod was 4 s earlier, then a new pod | real (pod shutting down) |

The false failure on 2026-10-23, in order: `worker-default-4` came back on a new pod and registered at 08:17:24, polled at
08:17:25, got the job and started it at 08:17:30. At 08:17:34 GC's status call could not resolve the pod's DNS name and the
job was set to FAILED; it finished normally 38 s later. The worker StatefulSet's headless service has no
`publishNotReadyAddresses` and the workers have no readiness probe, so the exact reason the name did not resolve yet is not
known (endpoint propagation or negative DNS caching right after the restart). The window opens on every worker restart: the
worker takes a job within seconds of registering.

The late FINISHED overwrote FAILED, so nothing was lost here; the job showed FAILED for 38 s. A long job would show FAILED for
its whole run.

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
3. Explicit timeouts on `WorkerClient`: done in v1.5.2 (`e46ca54`); they make this path more frequent, not less.

The long-term version is lease expiry instead of probing ([QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md)).

## Test

- Unit test: `getWorkerInfo` throws twice, then returns RUNNING with the right PID. The job must stay RUNNING.
- Unit test: `getWorkerInfo` throws on 3 rounds over 60 s. The job becomes FAILED.
- Unit test: the worker answers IDLE. The job becomes FAILED in that round.

## Related

- [KB-001](../known-bugs/KB-001-process-gc-stops-forever.md): the same GC round can also stop GC for good.
- [BUG-021](BUG-021-kill-overwritten-by-late-report.md): fix together; the state guard makes false FAILED permanent.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): lease-based liveness instead of probing.
