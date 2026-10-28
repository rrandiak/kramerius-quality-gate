# Run 06 — manager–worker communication

## Current source flow

This review uses the checked-out `process-platform` source, not a revision-matched production deployment. Production has one observed process-manager pod and multiple workers (Run 01), but no dispatch, connection, polling, or recovery metric has yet been collected. The current design is **already worker-initiated for work acquisition**. The manager remains the database authority for process records and initiates calls to workers for logs, status, kill, and directory cleanup.

```mermaid
sequenceDiagram
    participant Caller
    participant Manager
    participant DB
    participant Worker
    participant Plugin
    Caller->>Manager: schedule main process
    Manager->>DB: insert PLANNED
    loop while idle
        Worker->>Manager: GET next_process/{workerId}
        Manager->>DB: read PLANNED; select by tags/batch affinity
        Manager->>DB: set workerId; set NOT_RUNNING
        Manager-->>Worker: scheduled process or 404
    end
    Worker->>Plugin: launch child JVM
    Plugin->>Manager: PUT pid; PUT RUNNING
    Plugin->>Manager: PUT FINISHED/WARNING/FAILED
    Plugin-->>Worker: exit
    Manager->>Worker: GET info/logs or DELETE kill/directory
```

Source anchors: `WorkerLoop.java:42–106` polls, executes one child JVM synchronously, then sleeps when idle; `WorkerConfiguration.java:97–108` has a source default idle sleep of one second. `ManagerClient.java:113–139` treats 404 as no work. `ForWorkerEndpoint.java:78–112` exposes claim and state calls. `ProcessService.java:77–113,160–176,279–289` stores schedule and state, selects by strategy, and assigns the worker. `PluginStarter.java:60–101` reports PID, RUNNING, and terminal state. `WorkerClient.java:56–135` calls worker endpoints for kill and logs. `GCTask.java:35–76` checks RUNNING tasks against worker status. Effective production polling settings and request rates are unverified.

The manager serializes `getNextScheduledProcess` with a Java `synchronized` method, reads all `PLANNED` records, selects a matching job, then performs separate `updateWorkerId` and `updateState(NOT_RUNNING)` database statements. The synchronization applies to one manager JVM; it is not a database-level claim. The source has no lease or claim token on this path. A claimed job can be stranded if the response is lost or the worker stops before the child reports RUNNING. The GC scan handles RUNNING jobs, not NOT_RUNNING jobs. Conversely, a transient manager-to-worker status failure makes the GC mark a RUNNING job FAILED, even if its child still runs. These are source-derived failure scenarios to reproduce; incidence in production is unknown.

## Responsibilities and failure semantics

| Operation | Current initiator and authority | Failure question |
| --- | --- | --- |
| Schedule main/subprocess | Caller or plugin -> manager; manager DB owns `PLANNED` and batch records. | Are duplicate schedule requests idempotent? What links subprocess creation to parent completion/cancellation? |
| Acquire work | Idle worker -> manager `next_process`; manager selects by tags/batch affinity and stores assignment. | Atomic claim across manager replicas? What recovers `NOT_RUNNING` after a lost response or dead worker? |
| Run and progress | Worker launches child JVM; plugin reports PID, state, description and subprocesses back to manager. | What happens when state updates fail after work succeeded, or when plugin JVM exits before a terminal report? How are progress/logs correlated? |
| Logs and info | Manager -> worker HTTP; logs reside with worker. | Are logs retained and readable after worker loss or pod replacement? Does fetching a full log hold a connection/resource indefinitely? |
| Cancel/kill | Manager -> worker kill endpoint, then manager updates DB state. | Can a late FINISHED report overwrite KILLED? What happens if the kill call times out while the child remains alive? |
| Recovery | Manager GC probes workers for RUNNING tasks. | Is temporary network loss distinguishable from process death? How are `NOT_RUNNING` claims reclaimed safely? |

`WorkerLoop.java:78–91` catches an unexpected polling exception and calls `stop()`, ending the daemon loop. A transient manager outage can therefore leave an otherwise healthy worker idle until restart. `ManagerClient` and `WorkerClient` construct pooling HTTP clients with default `RequestConfig.custom().build()`; effective connect/response timeouts and pool behavior need runtime confirmation. `PluginStarter` catches failures while reporting terminal state, but a child process's exit code alone does not durably update the manager record. These are reasons to test recovery before optimizing polling frequency.

## Options to compare

| Option | Technical fit | What it must still solve |
| --- | --- | --- |
| Harden current REST polling | Smallest architectural change; worker-initiated claim already exists. Add bounded timeouts, retry/backoff with jitter, health visibility, atomic DB claim/lease, claim token and idempotent state transitions. Tune idle polling from measured traffic and dispatch objective. | DB contention from polling, stale claims, terminal-state races, manager multi-replica safety, and log availability. |
| REST long polling or worker-initiated streaming | Can reduce empty polls while keeping worker-initiated connectivity. Useful only if idle request volume or dispatch delay is material. | Server-held connections, restart/disconnect handling, claim lease and idempotency remain; endpoint timeouts/load balancers must permit waits. |
| Message broker for work notifications or delivery | May decouple availability and reduce polling, and can handle bursts. Use a notification plus DB claim or an explicit durable work queue. | Broker operations, duplicate/redelivery, ordering, dead-letter/recovery, cancellation and visibility; manager DB remains authority unless ownership is deliberately redesigned. Transport alone does not repair state semantics. |

The source does **not** justify reversing acquisition direction: workers already pull. A first recommendation should be conditional on measured dispatch latency, idle request load, DB query cost, and failure behavior. If polling cost is low, retain REST and focus on atomic claims/recovery. If empty polls dominate manager/DB load, compare longer polling or notifications after the correctness contract is fixed. Messaging should require a measured availability or capacity benefit that covers its extra operational and semantic cost.

## Controlled measurement and test run

1. Record deployed manager/worker revisions, effective `WORKER_LOOP_SLEEP_SECS`, manager replica count, DB pool settings, HTTP client timeouts, and process-state distribution. Aggregate request count and latency for `next_process`, registration, state/PID updates, info/log calls, and kill, by worker class and hour. Measure schedule-to-claim, claim-to-child-start, start-to-first-progress, completion-report delay, idle-worker fraction, and manager DB CPU/query time.
2. Reproduce current behavior in isolation: manager unavailable for one poll then restored; worker exits after claim but before RUNNING; response lost after DB claim; plugin completes while terminal update fails; manager cannot reach a still-running worker during GC; kill races FINISHED; manager restart and two manager replicas. Verify each process ends in exactly one explainable state, with safe retry or operator recovery and no duplicate side effect.
3. Specify authority: manager DB owns process ID, state, assignment, and batch linkage; worker owns child lifecycle and local logs until uploaded/retained. Define a lease expiry, heartbeat/renewal cadence, fencing token, retry eligibility, cancellation acknowledgement, and idempotency key for plugin effects. Distinguish *at-least-once dispatch* from *exactly-once side effects*; the latter requires plugin-specific idempotency or transactional boundaries.
4. Benchmark the hardened REST baseline under idle, burst, long-running, and failure workloads. If needed, compare one alternative (long polling or broker notification) with the same claim/state semantics. Report dispatch and completion p50/p95/p99, successful jobs/hour, idle request rate, DB/manager/worker utilization, recovery time, duplicate attempts, and operational cost. Keep actual import/index job duration separate from scheduler delay.

No measured communication overhead or speed benefit is available yet. The small first pilot is a **lost-claim/restart test** plus schedule-to-start instrumentation in staging; it resolves whether the current state model is safe before any transport experiment.
