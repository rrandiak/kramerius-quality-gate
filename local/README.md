# Local k3d benchmark

All deployment commands target the separate `qg` k3d cluster and `qg` namespace.
The HTTP runner accepts only a loopback URL, and its Kubernetes fingerprint uses
only context `k3d-qg`. Nothing in this workflow needs production credentials.

## Source and dependency map

The six `apps/` submodules pin the application checkouts. Kramerius 7.2.3 uses
Akubra 1.7, Hazelcast locks 2.0, and process-platform 1.5.2. The build script
publishes those dependencies into `.m2-qg/`; it exports process-platform's
`v1.5.2` tag from the submodule without changing its checkout. Kramerius and
the curator worker are built with Jib. Solr 9.6.1 uses the generated Kramerius
standalone core schemas. The browser client is pinned but is not needed for
the API slice. The chart deploys Kramerius public and curator, the worker,
process manager, three PostgreSQL databases, Hazelcast, gateway and Redis.
`local/dependencies.yaml` adds Solr, local Keycloak, a deterministic image
fixture, and an OpenTelemetry collector.

## Exact commands

From the repository root, with Docker, k3d, kubectl, Helm, Java 21 and Python
installed:

```sh
git submodule update --init --recursive
make install
QG_BUILD_MODE=source bash local/build.sh
bash local/up.sh
export KUBECONFIG="$PWD/.build-qg/kubeconfig-qg.yaml"
kubectl --context k3d-qg -n qg port-forward svc/gateway-openresty 8080:80
```

In another terminal:

```sh
export KUBECONFIG="$PWD/.build-qg/kubeconfig-qg.yaml"
kubectl --context k3d-qg -n qg port-forward svc/qg-keycloak 8081:8080
```

In a third terminal:

```sh
export KUBECONFIG="$PWD/.build-qg/kubeconfig-qg.yaml"
export QG_TOKEN="$(.venv/bin/python local/qg_token.py)"
.venv/bin/python local/seed.py --tier small
.venv/bin/qg bench --corpus corpora/tiny-local-v1-s1-p24/data \
  --out runs/small-1 --scenarios search,thumb --iterations 10 \
  --concurrency 1 --cache-state warm --gates gates.example.yaml
bash local/collect-traces.sh runs/small-1
.venv/bin/qg compare runs/small-1/run.json runs/small-2/run.json
```

`--tier medium` uses 1,000 requested pages; `--tier large` uses 10,000.
`--pages N` overrides the tier. The generator may emit more than N pages to
finish a document unit. The local spec, generated corpus summary, manifest,
and import result stay under `corpora/`. Runs stay under `runs/` and are never
overwritten. Every sample stores a trace ID. `qg traces` joins matching OTLP
JSON spans from the collector and reports component span totals. Nested spans
can overlap, so these values are diagnostic timings, not fractions of wall time.
The seed command refreshes its local admin token while waiting; use `--resume`
with the same tier, seed, and pages to monitor an import already scheduled.
The local `lp.xml` caps import and indexing child JVM heaps for the single-node
profile, and `local/up.sh` mounts it on both Kramerius pods. The worker has a 1536 MiB
limit so its Tomcat process and a child JVM can coexist.

The `run.json` fingerprint records submodule revisions, corpus hashes and
settings, configuration hash, image tags and runtime image IDs, pod resource
requests and limits, host details, cache label and concurrency. The report
shows correctness, p95 latency, throughput, errors, optional resource
snapshots and trace coverage. `gates.example.yaml` contains only correctness
limits; numerical performance and resource limits must be set deliberately
after collecting a baseline on the same host.

For a prebuilt image path, `QG_BUILD_MODE=prebuilt bash local/build.sh` pulls
the exact tags in `local/values.yaml`. A local source build is preferred for
comparing application revisions. Inspect `docker image inspect` and the
`run.json` runtime image IDs before comparing runs.

## Local lifecycle

`local/up.sh` creates `qg` only if absent, applies static hostPath PVCs, loads
the built images, and waits for deployments. Corpus files are copied to the
worker import PVC, and the local admin API schedules an `import` process with
indexing enabled. The image fixture serves deterministic JPEGs for generated
external datastream URLs. The import step waits for a terminal process state.
To reset cache state for cold runs, recreate only the `qg` cluster and record
that action in `--cache-state`; the default benchmark label is `warm`.

This first slice exercises search and thumbnail opening through Kramerius.
The runner also supports item structure, IIIF info, and OCR reads by selecting
`--scenarios search,item,thumb,iiif_info,ocr`. Import is performed by the seed
command. Administration, failure and recovery workloads still need dedicated
scenario implementations and verified local runs.
