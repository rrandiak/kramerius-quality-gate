# Kramerius Quality Gate

Benchmarking and validation framework for Kramerius releases, storage and infrastructure.
See `PLAN.md` for the pitch and `SCRATCH_PLAN.md` for the working plan.

The implementation on `main` now includes the six requested application
submodules, a source build and local k3d deployment profile, versioned FOXML
corpus seeding, an HTTP benchmark runner, trace joining, comparison and
configurable gates. See [local/README.md](local/README.md) for commands and
the current coverage limits.

`main` contains the quality-gate tooling, the [review authoring rules](RULES.md), and the review templates and conventions in [`review/`](review/README.md). The Kramerius/Akubra/process-platform review itself is on the branch `kramerius-review`: start at its `REVIEW.md` and `review/README.md`. The uppercase `PLAN.md` remains the quality-gate project pitch.

Keep benchmark and tooling work on `main`. The review branch is published as one squashed commit on top of `main`; its working history is not published.

```sh
make install
make gen SPEC=specs/mzk-like.yaml PAGES=10000   # synthetic FOXML corpus
make check test
```
