# Processing boundary — scheduling, worker execution, and state authority

This source-only map refines [Run 06](06-process-communication.md) and the processing block in [Run 09](09-service-boundaries.md). The checked-out revision is not matched to the deployed manager/worker images. No tests, production queries, or application changes were made.

```mermaid
sequenceDiagram
    participant Curator
    participant Manager
    participant DB
    participant Worker
    participant Child
    Curator->>Manager: schedule(profile, payload)
    Manager->>DB: insert PLANNED with processId
    Worker->>Manager: poll next work
    Manager->>DB: select PLANNED; set workerId and NOT_RUNNING
    Manager-->>Worker: processId, profile, payload
    Worker->>Child: launch JVM
    Child->>Manager: PID, RUNNING, terminal state
    Manager->>DB: update state/timestamps
```

`APIProcessScheduler.java:22–35` submits a curator job through the process-manager client. `ProcessService.scheduleMainProcess` validates payload and inserts a new UUID job in PLANNED (`ProcessService.java:78–91`). An idle worker polls, and the manager's synchronized method loads PLANNED rows, chooses one, and performs separate worker/status updates (`ProcessService.java:160–176`). The worker launches one child JVM per claimed job (`WorkerLoop.java:42–106`), while `PluginStarter.java:80–110` sends PID, RUNNING, and terminal reports. This is already worker-initiated acquisition. B6–B8 cover poll-loop exit, stranded claims, and GC false failures; B16 covers log proxy response handling.

## New source finding

**B25 / high — terminal process state can be overwritten by a late report.** `ProcessService.updateState` passes any requested state to `ProcessDao.updateState` and then updates timestamps (`ProcessService.java:279–291`). The SQL is `UPDATE pcp_process SET status = ? WHERE process_id = ?` (`ProcessDao.java:251–260`): it checks existence, not current state, claim identity, or a state version. Thus a delayed FINISHED report can overwrite a FAILED state set by GC, or a late RUNNING report can move a previously terminal job back to RUNNING. The same unguarded API is used for worker/plugin reports and manager recovery paths. This is a confirmed source-level transition gap; production incidence is unknown.

Later validation in the separate environment: deliver reports out of order around GC, cancellation, and worker restart; observe status, timestamps, child liveness, and retry eligibility. Define allowed transitions and terminal-state precedence, then enforce them with a conditional DB update plus claim/fencing token. The status change and corresponding timestamp should be one transaction. Reconcile ambiguous outcomes instead of silently allowing any last writer to win.

## Ownership contract for a logical processing module

| Concern | Source owner | Contract before another transport/service split |
| --- | --- | --- |
| Job intent and identity | Manager DB creates process ID and PLANNED record (`ProcessService.java:78–113`). | Caller-supplied idempotency/operation key for retries; immutable profile/payload revision; explicit parent/batch ownership. Curator collection writes need a durable link to this job intent ([Run 17](17-curator-write-boundaries.md)). |
| Claim and dispatch | Manager selects from all PLANNED rows; worker pulls. | Atomic DB claim across manager replicas, lease/expiry, claim token, bounded queue-selection cost, safe recovery of NOT_RUNNING (B7). |
| Child execution and side effects | Worker launches JVM; plugin code may mutate Akubra, processing index, and search. | Plugin-specific idempotency/checkpointing and ownership of repository/search writes; a redelivered job must not double-apply destructive mutations. |
| State and recovery | Manager DB owns status; plugin reports state; GC probes RUNNING workers. | Guarded state machine and fencing (B8/B25), distinguish unreachable from dead, define cancellation acknowledgement and terminal-report precedence. |
| Logs and observability | Worker stores process logs; manager fetches them via HTTP. | Log retention across worker replacement, response lifecycle/status mapping (B16), correlation between process ID, child PID, attempts, and durable state. |

Changing REST polling to a broker or reversing communication would not close B6–B8/B25. The first design step is an explicit state/claim contract within the existing manager DB. A separate processing service already exists operationally; further decomposition should be justified by measured dispatch delay, backlog, DB load, worker utilization, and recovery behavior. Indexing job duration, image-opening interference, and healthy search latency should be measured separately from schedule-to-start time. No numerical gain or rollout recommendation follows from this source map.
