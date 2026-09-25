# Kramerius Quality Gate

Benchmarking and validation framework for Kramerius releases, storage and infrastructure.
See `PLAN.md` for the pitch and `SCRATCH_PLAN.md` for the working plan.

```sh
make install
make gen SPEC=specs/mzk-like.yaml PAGES=10000   # synthetic FOXML corpus
make check test
```
