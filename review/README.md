# Review

Conventions for a review of Kramerius and its components (Akubra, process-platform, the CDK, the web client): one entry
per file, meant to be shown to people outside the review, in the directory of its category. Evidence (reports,
measurements, diagrams) goes to `raw/`; entries link to it.

Start an entry from the template of its category: [`_template-perf.md`](_template-perf.md) for `PS`, `PM` and `PH`,
[`_template-qol.md`](_template-qol.md) for `QOL`, [`_template-bug.md`](_template-bug.md) for `BUG` and `WC`, and
[`_template-known-bug.md`](_template-known-bug.md) for `KB`. Within a category, numbers follow priority (higher severity
or impact first, then lower effort); new entries take the next free number, and IDs never change or get reused.

## Categories

The category says what fixing an entry gives and what to do with it next.

| Category | Directory, ID | Meaning | Next step |
| --- | --- | --- | --- |
| `perf-simple` | `perf-simple/`, `PS-` | Makes Kramerius faster or cheaper to run, with effort **XS–S**: one module, no new configuration, API or schema. | Open a pull request. |
| `perf-medium` | `perf-medium/`, `PM-` | The same, with effort **M**: a new component or configuration, still within one module. | Agree on the design, then a staging run under load. |
| `perf-hard` | `perf-hard/`, `PH-` | The same, with effort **L–XL**: a contract, storage format or several systems change. | Benchmark against a baseline, then decide. |
| `quality-of-life` | `quality-of-life/`, `QOL-` | Nothing returns a wrong result and nothing is measurably slow, but Kramerius becomes easier to run, observe, diagnose or develop: cleanup, telemetry, deployment, module structure, operational safety. | Discuss with maintainers; no urgency. |
| `bug` | `bugs/`, `BUG-` | Something does the wrong thing (wrong result, lost or stale data, failed request or job, wrong status, a failure reported as success), and no upstream issue reports it yet. | Open a new upstream issue. |
| `known-bug` | `known-bugs/`, `KB-` | An upstream issue already reports the same symptom; the entry adds what the issue lacks: the cause, a fix, production counts or a second path. | Comment on that issue. |
| `webclient-bug` | `webclient-bugs/`, `WC-` | A defect in the Kramerius web client (`kramerius-web-client-v3`), not in Kramerius or its components. `bugs/` and `known-bugs/` hold only Kramerius and its components. | Open an issue in the web client's repository. |

When an entry fits two categories, the first matching rule wins:

1. The defect is in the web client → `webclient-bug`.
2. An upstream issue reports the same symptom (not just a related one) → `known-bug`.
3. Something does the wrong thing → `bug`, even when the fix also speeds things up (e.g. a slow path that also makes requests fail).
4. The gain is time, load or storage → `perf-*`, with the tier taken from the entry's main effort, not its cheapest first step.
5. Otherwise → `quality-of-life`.

## Checked

Every entry about a specific defect or code-level cost (`BUG`, `KB`, `WC`, and `PS` entries of that kind) records how it was
confirmed:

| Field | Meaning |
| --- | --- |
| `checked` | the methods used: `source` (code read at a named revision), `test` (a test was run and failed before the fix), `production` (MZK logs, traces, databases or NGINX, read-only), `upstream-report` (an upstream issue reports the incident) |
| `checked_how` | one line: what was read, run or counted, at which revision; a test that is written but not run is said so here, not counted as `test` |
| `checked_on` | the date of the last check |
| `mzk_programmer_check` | who confirmed the defect, when and how (read the code, reproduced it, saw it in production), once an MZK programmer has; `null` until then. Entries known only from code also say so at the top of their evidence section. |

`production` means we looked, not that it was found: `checked_how` says what the look showed. A test that is written but
not run is not `test`.

## Effort

Effort is a size, not a time estimate. It is set by **what has to change**, so anyone can check it against
the code. An entry takes the **highest** size whose criteria it meets.

| Size | What changes | Verification needed |
| --- | --- | --- |
| **XS** | A few lines in one method or class. No behavior change beyond the defect. | One unit test. |
| **S** | One or a few classes in one module. No new configuration, API, schema or data change. | Unit tests. |
| **M** | A new component (thread, queue, cache, client) or several classes, still within one module. New configuration, or a behavior change people notice (e.g. delayed logs). | Staging run under load. |
| **L** | Several modules, or a contract changes: REST API, Solr schema, storage format, DB schema. Needs backward compatibility or a migration path. | Benchmark against a baseline, plus a rollback plan. |
| **XL** | Several systems (Kramerius, Akubra, process-platform, deployment), or the repository or index must be migrated. Needs a staged rollout and coordination with other institutions or CDK. | Benchmark campaign, plus a migration rehearsal. |

The header fields `touches`, `contracts` and `data_migration` record the facts the size is based on.
