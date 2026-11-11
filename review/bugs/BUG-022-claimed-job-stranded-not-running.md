---
id: BUG-022
former_id: WC-001
category: bug
title: A job that a worker claimed but never started stays NOT_RUNNING for good, and nothing retries or fails it
area: communication
severity: medium
effort: S                # GC sweep of stale claims, worker reports a failed launch, atomic claim
use_cases: [indexing, ingest, admin]
review_ref: [B7]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1375
checked: [source, production]
checked_how: "Read the claim path at process-platform da88e6a and 976dc4b; MZK process DB, all 41,814 jobs (2 stuck)"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-022 — A job that a worker claimed but never started stays NOT_RUNNING for good, and nothing retries or fails it

> **In one sentence:** the process manager marks a job NOT_RUNNING when it hands it to a worker, and only the plugin JVM
> moves it on to RUNNING, so if the handover is lost or the JVM dies before its first report, the job stays NOT_RUNNING with
> no retry, no failure and no alert, and its batch never completes.

## Upstream issue

[kramerius#1375](https://github.com/ceskaexpedice/kramerius/issues/1375) "Proces, ktorý si worker vzal, ale nespustil,
ostane navždy v stave NOT_RUNNING", opened by MZK on 2026-11-10 from this entry (filed in kramerius, the code is in
process-platform): cause (GC checks only RUNNING jobs, a NOT_RUNNING job is no longer PLANNED), the MZK numbers, how to
check it, since when and the fix (GC also checks NOT_RUNNING jobs and fails them after two rounds in which the worker
does not run them; the worker marks a job FAILED itself when the plugin JVM fails to start).

## Symptom

A scheduled job (reindex, import, licence change) shows **Not running** in the admin UI and never changes. Its batch also
shows **Not running**, because the batch state is the highest child state value and NOT_RUNNING (4) outranks FINISHED (0) and
FAILED (3). The work was never done. The only way out is for an admin to notice, kill the batch, and schedule it again.

## Cause

Deployed at MZK (checked 2026-11-11): the **workers** run process-platform **v1.5.2** (`285f1e5`, branch `hotfix/1.5.x`,
bundled in the Kramerius 7.2.2.4 worker images since 2026-10-08), the **process manager** ran **v1.5** (`4974929`, image
`ceskaexpedice/process-manager:1.5`, `process-common-1.5.jar`) through every incident below; it was upgraded to 1.5.2 on
2026-11-11 at 19:42 UTC. `GCTask`, `GCScheduler`, `WorkerLoop` and the worker registration are the same in v1.5, v1.5.2 and
`main` (`da88e6a`, which v1.5.2 is not merged into). v1.5.2 adds the "Issue #13" HTTP client timeouts (`aea65db` worker side,
`e46ca54` manager side) and a configurable manager DB pool.

`process-platform` `main` at `da88e6a` (unchanged in `976dc4b`):

- **Claim is two plain updates, with no lease.** `ProcessService.getNextScheduledProcess` (`ProcessService.java:160–176`)
  reads all PLANNED rows, picks one, then runs `processDao.updateWorkerId` and `processDao.updateState(NOT_RUNNING)`
  (`:174–175`). Both are unconditional `UPDATE pcp_process SET ... WHERE process_id = ?` statements in separate connections
  (`ProcessDao.java:237–263`). Nothing records when the claim was made or expects it to be confirmed.
- **Only the plugin JVM sets RUNNING.** `PluginStarter.main` reports RUNNING (`PluginStarter.java:83`) only after it has set up
  its streams, built the plugin context and the manager client, and reported its PID. Everything before that point is a gap
  in which a failure leaves the job NOT_RUNNING:
  - the HTTP response with the claimed job never reaches the worker (timeout, manager or worker pod restart);
  - the worker pod is stopped (deploy, eviction) after the claim and before the child JVM reports;
  - the child JVM fails to start or dies early (bad `jvmArgs` in the profile, memory, a missing class). `WorkerLoop` logs
    `Error during task execution` and moves on (`WorkerLoop.java:57–63`, comment: `// Optionally: retry, skip, or escalate`);
  - the child cannot reach the manager: the RUNNING report fails, and the FAILED report in the `catch` block
    (`PluginStarter.java:107–112`) goes through the same unreachable client.
- **The GC never looks at NOT_RUNNING.** `GCTask.run` checks only `ProcessState.RUNNING` rows (`GCTask.java:48`). A
  NOT_RUNNING row is not PLANNED either, so no worker selects it again.
- **Latent: claims are not atomic across managers.** The method is `synchronized`, which protects one manager JVM only. Two
  manager replicas could both select the same PLANNED row and hand it to two workers. The Helm chart pins the process manager
  to `replicas: 1` (`templates/process-manager/statefulset.yaml:12`), so this does not happen at MZK today; it is a reason to
  fix the claim with the database, not with a Java lock.

## Evidence and frequency

MZK production, `process-db`, read-only query on 2026-10-28 over all of `pcp_process` (41,814 jobs):

| Status | Jobs |
| --- | --- |
| FINISHED | 41,020 |
| FAILED | 760 |
| KILLED | 32 |
| **NOT_RUNNING** | **2** |

Both NOT_RUNNING jobs are single-job batches that have been stuck for weeks. Neither has a `started` time, and both have
`pid = 0`, so the plugin JVM never even reported its PID: the job was lost before `PluginStarter` reached the manager.

| Planned | Profile | Worker |
| --- | --- | --- |
| 2026-10-01 03:01 | `processing_rebuild_for_object` | `worker-default-1` |
| 2026-10-07 15:11 | `new_indexer_index_object` | `worker-default-3` |

Which gap caused them (lost response, pod restart, failed JVM start) cannot be told any more: worker traces only exist since
the 2026-10-27 deploy. It is rare (about 1 in 20,000 jobs), but each case is silent and permanent, and nobody had noticed
these two.

**Three more by 2026-11-11** (read-only query on `pcp_process`, `status = 4`; times local, as stored), again single-job
batches with no `started` and `pid = 0`:

| Planned | Profile | Worker |
| --- | --- | --- |
| 2026-11-04 03:15 | `processing_rebuild_for_object` | `worker-default-7` |
| 2026-11-05 05:05 | `processing_rebuild_for_object` | `worker-default-5` |
| 2026-11-06 04:51 | `new_indexer_index_object` | `worker-default-4` |

All three fall into the nights of 2026-11-04 to 2026-11-06, when the process manager was unreachable for hours (2026-11-04),
process-db dropped out and GC died ([KB-001](../known-bugs/KB-001-process-gc-stops-forever.md)), and worker loops ended
([KB-002](../known-bugs/KB-002-worker-loop-stops-on-poll-error.md)). So far: 5 stranded jobs, 3 of them in one week.

The conditions are common at MZK: KB-005 left 5 of 10 worker pods unregistered for over an hour after the 2026-10-27 deploy,
and every deploy restarts workers, which can land between claim and RUNNING.

## Impact

- Scheduled work silently does not happen: a reindex or licence change that the admin believes is queued.
- The batch never reaches a final state, so tools or people waiting for it wait for good.

## Fix

The smallest change, in process-platform only, with no schema change:

1. **Recover stale claims in the GC.** Extend `GCTask.run` to NOT_RUNNING rows: ask the claiming worker (as for RUNNING rows)
   and mark the job FAILED (or back to PLANNED, if the profile is safe to retry) when the worker is idle or running another
   PID on two consecutive GC passes. Two passes, not one, so that a job between claim and RUNNING is not failed, and so that
   one failed probe does not fail it either (see BUG-014).
2. **Report a failed launch from the worker.** When `PluginJvmLauncher.launchJvm` returns non-zero and the job is still
   NOT_RUNNING, the worker reports FAILED itself instead of only logging.
3. **Claim atomically.** Replace the read-then-two-updates with one statement that takes a single PLANNED row and sets
   `worker_id` and status together, e.g. `UPDATE ... WHERE process_id = (SELECT ... WHERE status = PLANNED ... FOR UPDATE SKIP
   LOCKED LIMIT 1) RETURNING ...`, with the profile filter in the subquery. This makes more than one manager replica safe.

A claim timestamp (`claimed` column) would let step 1 use a plain timeout instead of asking the worker, but it is a schema
change (size M).

## Test

- Manager unit test with an in-memory DAO: claim a job, never report RUNNING, run the GC twice with a worker that reports
  idle; the job must end FAILED (or PLANNED). Run it once more with a worker that reports the job's PID as running; the job
  must be left alone.
- Worker test: a `ScheduledProcess` whose main class does not exist; the worker must report FAILED for it.
- DAO integration test (PostgreSQL): two threads claim from one PLANNED row; exactly one gets it.

## Related

- [BUG-021](BUG-021-kill-overwritten-by-late-report.md): the same missing state guard; a killed NOT_RUNNING job can still
  report RUNNING.
- [BUG-014](BUG-014-gc-fails-running-job-on-one-probe-error.md): the GC's probe handling, which step 1 should reuse correctly.
- [KB-005](../known-bugs/KB-005-worker-never-starts-if-registration-fails.md): worker restarts and registration gaps widen the window.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): a worker heartbeat lease would cover claims as well.
