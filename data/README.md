# data

Calibration inputs and outputs. Nothing here is a benchmark corpus; generated
corpora live outside the repo.

- `raw/` — **not in git.** Dumps fetched from production instances: pid paths,
  model lists, FOXML samples. Large, and may contain production content.
  Files can be symlinks to where they were downloaded.
- `derived/` — in git. Statistics computed from `raw/` by `calibration/*.py`:
  numbers only, no titles, no pids, no content.

## raw/ inventory

| File | Line format | Source | Fetched |
|---|---|---|---|
| `periodical.paths.txt` | `<periodical>/<volume>[/<item>[/<sub>]]/<page>` pids, one line per page | MZK, all `root.model:periodical` pid_paths | 2026-09-10 |
| `periodical.models.txt` | `<pid>,<model>` for every non-page pid in `periodical.paths.txt` | MZK | 2026-09-25 |
| `other.paths-and-models.txt` | `<model path>,<pid path>` for every node under `-root.model:(monograph OR periodical)` (934k) | MZK | 2026-09-25 |
| `solr/children.<parent>.<child>.tsv` | `<parent pid>\t<direct child count>` for monograph→page, monograph→monographunit, monographunit→page | MZK client search API (`calibration/fetch_solr.py`) | 2026-09-25 |
| `solr/roots.tsv` | `<pid>\t<model>\t<licenses>\t<in_collections.direct>\t<in_collections>` for all `level:0` (317k) | same | 2026-09-25 |
| `solr/collections.tsv` | same columns for `model:collection` (819) | same | 2026-09-25 |
| `solr/aggregates.json` | facet counts: child models, licenses by level, direct collection members by model | same | 2026-09-25 |
| `periodical.alto-software.txt` | `<page pid>,<ALTO producer>` for periodical pages (symlink) | MZK | 2026-09-11 |
| `foxml/pids.txt`, `foxml/sample.tsv` | seeded stratified sample for archive export (`calibration/sample_pids.py --seed 1`); `sample.tsv` = pid, model, stratum | generated | 2026-09-25 |
| `foxml/<uuid>.xml` *(pending)* | `GET /search/api/admin/v7.0/repository/export?format=archive&pid=…` | MZK admin API | – |
