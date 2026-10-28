---
id: BUG-021
former_id: BUG-007
category: bug
title: Killing a batch does not stop a job that is still starting; its RUNNING report overwrites KILLED and it runs to the end
area: communication
severity: medium
effort: S                # guarded state update in the manager, plugin starter stops on a rejected report
use_cases: [indexing, ingest, admin]
review_ref: [B25]
upstream: null
checked: [source]
checked_how: "Read ProcessService at process-platform da88e6a; not observed"
checked_on: 2026-10-27
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-021 — Killing a batch does not stop a job that is still starting; its RUNNING report overwrites KILLED and it runs to the end

> **In one sentence:** the process manager accepts any state report for any process, so a job that was killed while its JVM
> was still starting reports RUNNING a moment later, the KILLED state is overwritten, and the job runs to the end, including
> whatever it writes to the repository and the index.

## Symptom

An admin kills a batch right after scheduling it (e.g. a wrong PID list for a reindex or a licence change). The admin UI shows
**Killed**, then a few seconds later **Running**, and later **Finished**. The job did its work.

## Cause

`process-platform` `main` at `da88e6a`:

- **No state guard.** `ProcessService.updateState` passes any state to `ProcessDao.updateState`
  (`UPDATE pcp_process SET status = ? WHERE process_id = ?`, `ProcessDao.java:251–263`). It does not check the current state, so a
  terminal state (KILLED, FAILED, FINISHED) can be replaced by any later report.
- **Kill only reaches RUNNING jobs.** `ProcessService.killBatch` (`ProcessService.java:227–242`) sends the kill to the worker only
  when `pid != 0 && status == RUNNING` (line 235). Every other process in the batch is only set to KILLED in the database.
- **A starting job reports RUNNING later.** After a worker claims a job (state NOT_RUNNING), it launches the plugin JVM.
  `PluginStarter.main` builds the plugin context, then reports the PID and then RUNNING (`PluginStarter.java:80–83`), runs the
  plugin, and reports FINISHED (line 85). If the batch was killed between the claim and the RUNNING report, the RUNNING report
  overwrites KILLED and nothing stops the plugin.
- **A failed kill call aborts the loop.** `workerClient.killProcessJvm` (line 236) has no `try`. If the worker cannot be
  reached, `killBatch` throws on that process: the remaining processes in the batch are neither killed nor marked KILLED, and
  the unreachable job keeps running and later overwrites KILLED with FINISHED.

The window between claim and RUNNING is the JVM start plus the plugin context setup, typically a few seconds. It is small, but
it is exactly when people kill a batch they have just scheduled by mistake.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.**

Source only, not yet observed. The process manager has been traced since 2026-10-27 (chart 1.3.2): a `PUT …/state/{id}`
server span with `RUNNING` shortly after a `killBatch` call for the same batch would confirm it.

## Impact

- A killed job can still change the repository and the search index. For destructive plugins (licence removal, delete tree,
  reindex with wrong parameters) the kill is the safety brake, and here it does not work.
- The final state in the admin UI is wrong (Finished instead of Killed), so the operator does not know the job ran.
- The same missing guard lets a late FINISHED overwrite FAILED set by the GC. That direction often ends with the true state,
  which is why the problem is easy to miss.

## Fix

1. **Guard transitions in the database.** `ProcessDao.updateState` becomes
   `UPDATE pcp_process SET status = ? WHERE process_id = ? AND status NOT IN (<terminal states>)`, and `updateState` returns
   whether the row changed. Allowed moves: PLANNED → NOT_RUNNING → RUNNING → terminal, and any non-terminal → KILLED.
2. **Tell the plugin when it was killed.** If the RUNNING report is rejected because the job is already terminal, the endpoint
   answers 409, and `PluginStarter` exits without running the plugin.
3. **Make `killBatch` complete.** Wrap each `killProcessJvm` in `try`, still mark the process KILLED, and report how many
   kill calls failed.

Step 1 alone fixes the wrong final state; step 2 is what actually stops the work.

## Test

- Unit test on `ProcessService`: KILLED, then `updateState(RUNNING)` → rejected, state stays KILLED.
- Integration test: schedule a batch whose plugin sleeps 10 s in its context setup, kill the batch after 1 s. The plugin must
  not run and the final state must be KILLED.
- `killBatch` with one worker unreachable: every process ends KILLED, and the call reports the failed kill.

## Missing upstream

Not reported. An issue for `ceskaexpedice/process-platform` should state:

- **Finding:** `killBatch` (`ProcessService.java:227–242`) sends a kill to the worker only for jobs that are RUNNING with
  a PID. A job the worker has already claimed (NOT_RUNNING) whose JVM is still starting is only set to KILLED in the
  database. A few seconds later `PluginStarter` reports RUNNING (`PluginStarter.java:83`), `ProcessDao.updateState`
  (`UPDATE … WHERE process_id = ?`) overwrites KILLED, and the plugin runs to the end.
- **Fix:** a conditional update (`AND status NOT IN (<terminal states>)`), answer 409 to a rejected RUNNING report, and do
  not start the plugin in `PluginStarter` in that case. Wrap `killProcessJvm` in `killBatch` in a `try`, so an unreachable
  worker does not stop the kill of the rest of the batch.

## Related

- [KB-001](../known-bugs/KB-001-process-gc-stops-forever.md) and review B8: the GC writes FAILED through the same unguarded update.
- [QOL-004](../quality-of-life/QOL-004-worker-initiated-control.md): claim tokens and kill-via-heartbeat make this fix part of a
  larger contract.
