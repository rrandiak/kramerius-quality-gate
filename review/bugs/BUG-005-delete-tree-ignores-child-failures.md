---
id: BUG-005
former_id: BUG-034
category: bug
title: Delete-tree job ignores failed descendants in its result
area: storage
severity: high
effort: XS
use_cases: [admin, storage]
review_ref: [H4]
upstream: https://github.com/ceskaexpedice/kramerius/issues/1381
touches: [kramerius/processes/dnntflag]
contracts: []
data_migration: false
checked: [source, production]
checked_how: "Read DeleteTreeProcess at Kramerius 560676c and 3c8bacca (7.2.2.4, same on master); error logs of all 631 delete-tree jobs at MZK via the process-manager log API; search index and MODS of the 397 affected pages"
checked_on: 2026-11-11
mzk_programmer_check: null  # who confirmed it, when and how, once an MZK programmer has; null = not yet
---

# BUG-005 — Delete-tree job ignores failed descendants in its result

> **In one sentence:** A delete-tree job can report success even when a descendant deletion returned failure.

## Upstream issue

[kramerius#1381](https://github.com/ceskaexpedice/kramerius/issues/1381) "Mazanie stromu skončí ako úspešné, aj keď sa časť
potomkov nepodarilo zmazať", opened by MZK on 2026-11-11 from this entry: cause (`someProblem &= deleteTree(...)` drops every
child result), the MZK log scan (37 FINISHED jobs hiding 464 failed deletions, 0 WARNING ever), a repro on a test tree,
since when (`8c4bfac27`, `v7.0.3`) and the fix (`someProblem |= !deleteTree(...)`).

## Symptom

The job can finish without a warning while a child object was not fully deleted in inconsistency-tolerant mode.

## Cause

`DeleteTreeProcess.java:104–114@560676c` (same lines at `3c8bacca`, 7.2.2.4) initializes `someProblem` to false and then uses `someProblem &= deleteTree(child, ...)`. Bitwise AND evaluates the child call but leaves false unchanged, so failed child returns are lost. The method returns `!someProblem` at line 201, and the top-level `deleteMain` raises a warning only when that result is false (`DeleteTreeProcess.java:92–96@560676c`).

## Evidence and frequency

**Seen in production at MZK: 37 delete-tree jobs since July 2026 hid 464 failed deletions and ended FINISHED.**

The bug matters only with `ignoreIncosistencies=true`. `pcp_process` on 2026-11-11: 631 `delete_tree` jobs since
2026-04-09, 299 with `ignoreIncosistencies=true` and 332 (all on 2026-08-25) without the value in the payload, which logged
failures and went on the same way; 0 ended WARNING. Scan of the error log of each job
(`GET /process-manager/api/process/{id}/log/err`, 615 jobs still have one) for `SEVERE` records logged by
`DeleteTreeProcess.deleteTree` (each sets `someProblem = true`; the "multiple own parents" record does not):

| | Count |
| --- | --- |
| jobs with such records | 37, all FINISHED (13. 7. – 10. 11. 2026) |
| hidden failed deletions | 464 (max 141 in one job, 2026-07-13) |
| of them: page whose FOXML file was missing (`FileNotFoundException` in `AkubraDOManager.readObjectFromStorage`) | 403 (397 pages) |
| of them: `NullPointerException` from Akubra | 39 |
| of them: Solr error in the index delete | 22 |

When the repository delete throws, `deleteObject` exits before `indexerAccess.deleteById(pid)`
(`DeleteTreeProcess.java:278–303` at `3c8bacca`), so the search document stays. At MZK this left no lasting damage: all 397
pages are in the search index and the repository today, indexed on the day of their delete job or later, i.e. the titles were
imported again (the usual delete-and-reimport workflow). Whether the 39 + 22 other failures left anything behind was not
checked.

## Impact

Operators can treat a partial deletion as complete. Repository and search-index remnants may need manual reconciliation.

## Fix

Replace the accumulation with `someProblem |= !deleteTree(child, ...)` so every child is evaluated and any false result is retained.

## Test

Use an isolated recursive deletion fixture whose child returns false and whose root has no local failure. Assert that the top-level result is a warning.

## Related

[Bug hunt 2, H4](../raw/26-bug-hunt-2.md#candidates).
