---
id: BUG-029
former_id: null
category: bug
title: The statistics report's one-at-a-time semaphore gains a permit each time a waiting request is interrupted
area: admin
severity: low
effort: XS               # move acquire before the try in one method
touches: [kramerius/rest (admin v7 statistics)]
contracts: []
data_migration: false
use_cases: [admin]
review_ref: []
upstream: null
checked: [source]
checked_how: "Read StatisticsResource at Kramerius 560676c; not observed"
checked_on: 2026-10-28
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-029 — The statistics report's one-at-a-time semaphore gains a permit each time a waiting request is interrupted

> **In one sentence:** the admin statistics report is meant to run one at a time behind a semaphore with one permit, but
> `release()` runs in `finally` even when `acquire()` was interrupted and never got a permit, so every interrupted wait adds
> a permit and reports can then run in parallel.

## Symptom

None visible directly; after an interrupted wait, two or more statistics reports can run at the same time, each scanning
the `logs` core.

## Cause

Kramerius `560676c`, `rest/.../apiNew/admin/v70/statistics/StatisticsResource.java`:

- `STATISTIC_SEMAPHORE = new Semaphore(1)` (line 122), with the comment "only one report at the time" (line 534).
- `STATISTIC_SEMAPHORE.acquire()` is the first statement inside the `try` (line 530); the `finally` calls `release()`
  unconditionally (line 552). If `acquire()` throws `InterruptedException`, the `catch` at line 549 turns it into an error
  response, and the `finally` still releases a permit that was never taken.

## Evidence and frequency

**Known from code only; not confirmed by an MZK programmer and not seen in production.** Request threads are rarely
interrupted, so this needs a container shutdown or a client disconnect handled by interruption while a report is
waiting.

## Impact

Reports meant to run one at a time can run concurrently and load Solr's `logs` core more than intended. Admin users only.

## Fix

Call `acquire()` before the `try` (or set a flag after a successful `acquire()` and release only when it is set), and
restore the interrupt status in the `catch`.

## Test

Unit test: interrupt a thread blocked in the report's `acquire()`; afterwards `availablePermits()` must still be 0 while
another report holds the permit (today it becomes 1, then 2 after release).

## Missing upstream

Not reported. An issue for `ceskaexpedice/kramerius` should state:

- **Finding:** in `StatisticsResource` the report calls `acquire()` inside the `try` (line 530) and `release()` in
  `finally` (line 552), so an interrupted wait adds a permit to the one-permit semaphore (line 122).
- **Fix:** acquire before the `try`, or release only after a successful acquire; restore the interrupt flag.

## Related

- [PM-003](../perf-medium/PM-003-batched-access-log-writer.md): the `logs` core these reports read.
