# Kramerius Quality Gate

Benchmarking and validation framework for Kramerius releases, storage and infrastructure.
See `PLAN.md` for the pitch and `SCRATCH_PLAN.md` for the working plan.

`main` contains the reusable quality-gate tooling and the [review authoring rules](RULES.md). The current Kramerius/Akubra/process-platform review lives on `review/kramerius-architecture`, with a separate checkout at `../kramerius-quality-gate-review`. Start at that branch's `REVIEW.md`; its `review-plan.md` is the review checklist. The uppercase `PLAN.md` on `main` remains the quality-gate project pitch.

Keep benchmark/tooling work on `main`. Bring reusable improvements from the review branch back through focused commits or cherry-picks after review; the entire review branch is a working history and is not intended as a single merge into `main`. Both branches are local until explicitly pushed.

```sh
make install
make gen SPEC=specs/mzk-like.yaml PAGES=10000   # synthetic FOXML corpus
make check test
```
