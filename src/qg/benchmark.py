"""Local, deterministic HTTP workload and machine-readable result format."""

import hashlib
import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _git_revision(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cluster_fingerprint(context: str) -> dict[str, Any]:
    if context != "k3d-qg":
        raise ValueError("only the k3d-qg Kubernetes context is accepted")
    completed = subprocess.run(
        ["kubectl", "--context", context, "-n", "qg", "get", "pods", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"cannot fingerprint local cluster: {completed.stderr.strip()}")
    pods = json.loads(completed.stdout)
    return {
        pod["metadata"]["name"]: {
            "node": pod.get("spec", {}).get("nodeName"),
            "containers": [
                {
                    "name": container["name"],
                    "image": container["image"],
                    "resources": container.get("resources", {}),
                    "image_id": next(
                        (
                            status.get("imageID")
                            for status in pod.get("status", {}).get("containerStatuses", [])
                            if status["name"] == container["name"]
                        ),
                        None,
                    ),
                    "restarts": next(
                        (
                            status.get("restartCount")
                            for status in pod.get("status", {}).get("containerStatuses", [])
                            if status["name"] == container["name"]
                        ),
                        None,
                    ),
                }
                for container in pod.get("spec", {}).get("containers", [])
            ],
        }
        for pod in pods.get("items", [])
    }


def _resource_snapshot(context: str, cluster: dict[str, Any]) -> dict[str, int] | None:
    nodes = {pod["node"] for pod in cluster.values() if pod["node"]}
    if len(nodes) != 1:
        return None
    node = nodes.pop()
    completed = subprocess.run(
        [
            "kubectl",
            "--context",
            context,
            "get",
            "--raw",
            f"/api/v1/nodes/{node}/proxy/stats/summary",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode:
        return None
    summary = json.loads(completed.stdout)
    qg_pods = [
        pod for pod in summary.get("pods", []) if pod.get("podRef", {}).get("namespace") == "qg"
    ]
    return {
        "memory_working_set_bytes": sum(
            int(pod.get("memory", {}).get("workingSetBytes") or 0) for pod in qg_pods
        ),
        "cpu_usage_core_nanoseconds": sum(
            int(pod.get("cpu", {}).get("usageCoreNanoSeconds") or 0) for pod in qg_pods
        ),
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.5)))]


def _request(url: str, trace_id: str, timeout: float) -> tuple[int, bytes, str, float]:
    traceparent = f"00-{trace_id}-{os.urandom(8).hex()}-01"
    request = urllib.request.Request(
        url, headers={"traceparent": traceparent, "X-QG-Trace-Id": trace_id}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("Content-Type", ""),
                time.perf_counter() - started,
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.read(),
            error.headers.get("Content-Type", ""),
            time.perf_counter() - started,
        )


def _scenario(base_url: str, name: str, pid: str) -> tuple[str, str]:
    quoted = urllib.parse.quote(pid, safe=":")
    query = urllib.parse.quote(f'pid:"{pid}"')
    prefix = f"{base_url.rstrip('/')}/search/api/client/v7.0"
    paths = {
        "search": f"/search?q={query}&rows=1&wt=json",
        "item": f"/items/{quoted}/info/structure",
        "thumb": f"/items/{quoted}/image/thumb",
        "iiif_info": f"/items/{quoted}/image/iiif/info.json",
        "ocr": f"/items/{quoted}/ocr/text",
    }
    return prefix + paths[name], name


def _correct(name: str, status: int, body: bytes, content_type: str, pid: str) -> bool:
    if status != 200:
        return False
    if name == "thumb":
        return body.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"))
    if name == "ocr":
        return len(body.strip()) > 0
    try:
        parsed = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        return False
    if name == "search":
        response = parsed.get("response", {})
        return response.get("numFound", 0) >= 1 and any(
            doc.get("pid") == pid for doc in response.get("docs", [])
        )
    if name == "iiif_info":
        return int(parsed.get("width", 0)) > 0 and int(parsed.get("height", 0)) > 0
    return bool(parsed) and ("json" in content_type.lower())


def _one(base_url: str, name: str, pid: str, iteration: int, timeout: float) -> dict[str, Any]:
    trace_id = uuid.uuid4().hex
    url, _ = _scenario(base_url, name, pid)
    try:
        status, body, content_type, seconds = _request(url, trace_id, timeout)
        correct = _correct(name, status, body, content_type, pid)
        error = None if correct else body[:200].decode("utf-8", "replace")
    except (OSError, TimeoutError) as exc:
        status, body, seconds, correct, error = 0, b"", timeout, False, str(exc)
    return {
        "scenario_id": name,
        "iteration": iteration,
        "pid": pid,
        "trace_id": trace_id,
        "status": status,
        "correct": correct,
        "duration_ms": round(seconds * 1000, 3),
        "bytes": len(body),
        "error": error,
    }


def _image_pids(corpus: Path) -> tuple[str, str]:
    rows = (json.loads(line) for line in (corpus / "manifest.jsonl").read_text().splitlines())
    pages = [row["pid"] for row in rows if row["model"] == "page"]
    roots = [
        row["pid"]
        for row in (
            json.loads(line) for line in (corpus / "manifest.jsonl").read_text().splitlines()
        )
        if row["parent"] is None
    ]
    if not pages or not roots:
        raise ValueError("corpus must contain a root and a page")
    return str(roots[0]), str(pages[0])


def run(
    corpus: Path,
    base_url: str,
    out: Path,
    *,
    iterations: int,
    concurrency: int,
    cache_state: str,
    scenarios: list[str],
    timeout: float,
    config: Path | None = None,
    kube_context: str | None = None,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "runner accepts only a loopback HTTP port-forward; production access is disabled"
        )
    if iterations < 1 or concurrency < 1:
        raise ValueError("iterations and concurrency must be positive")
    root_pid, page_pid = _image_pids(corpus)
    known = {"search", "item", "thumb", "iiif_info", "ocr"}
    if not scenarios or set(scenarios) - known:
        raise ValueError(f"scenarios must be selected from {sorted(known)}")
    cluster = _cluster_fingerprint(kube_context) if kube_context else None
    resources_before = (
        _resource_snapshot(kube_context, cluster) if kube_context and cluster else None
    )
    run_id = uuid.uuid4().hex
    jobs = [
        (name, root_pid if name == "search" else page_pid, index)
        for name in scenarios
        for index in range(iterations)
    ]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        samples = list(pool.map(lambda job: _one(base_url, job[0], job[1], job[2], timeout), jobs))
    elapsed = time.perf_counter() - started
    resources_after = (
        _resource_snapshot(kube_context, cluster) if kube_context and cluster else None
    )
    workspace = Path(__file__).resolve().parents[2]
    submodules = {
        name: _git_revision(workspace / "apps" / name)
        for name in (
            "kramerius",
            "kramerius-web-client-v3",
            "kramerius-helm-chart",
            "process-platform",
            "akubra",
            "hazelcast-locks-server",
        )
    }
    corpus_summary = json.loads((corpus / "corpus.json").read_text())
    config_data = yaml.safe_load(config.read_text()) if config else {}
    image_tags = {}
    for component in (
        "krameriusPublic",
        "krameriusCurator",
        "processManager",
        "workersDefaults",
        "hazelcast",
    ):
        image = config_data.get(component, {}).get("image", {})
        if image:
            image_tags[component] = f"{image['repository']}:{image['tag']}"
    fingerprint = {
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "quality_gate_revision": _git_revision(workspace),
        "applications": submodules,
        "corpus": corpus_summary,
        "corpus_sha256": _sha256(corpus / "corpus.json"),
        "manifest_sha256": _sha256(corpus / "manifest.jsonl"),
        "configuration_sha256": _sha256(config) if config else None,
        "image_tags": image_tags,
        "deployment_resources": {
            component: config_data.get(component, {}).get("resources") for component in image_tags
        },
        "base_url": base_url,
        "cache_state": cache_state,
        "concurrency": concurrency,
        "iterations": iterations,
        "timeout_s": timeout,
        "kubernetes": cluster,
    }
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "elapsed_s": round(elapsed, 3),
        "fingerprint": fingerprint,
        "samples": samples,
        "summary": summarize(samples, elapsed),
        "resources": {
            "before": resources_before,
            "after": resources_after,
            "cpu_usage_core_nanoseconds_delta": (
                resources_after["cpu_usage_core_nanoseconds"]
                - resources_before["cpu_usage_core_nanoseconds"]
                if resources_before and resources_after
                else None
            ),
        },
    }
    out.mkdir(parents=True, exist_ok=False)
    (out / "run.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out / "report.md").write_text(report(result))
    return result


def summarize(samples: list[dict[str, Any]], elapsed_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in sorted({sample["scenario_id"] for sample in samples}):
        subset = [sample for sample in samples if sample["scenario_id"] == name]
        durations = [sample["duration_ms"] for sample in subset]
        result[name] = {
            "requests": len(subset),
            "correct": sum(bool(sample["correct"]) for sample in subset),
            "errors": sum(not sample["correct"] for sample in subset),
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
            "p99_ms": _percentile(durations, 0.99),
            "throughput_rps": round(len(subset) / elapsed_s, 3) if elapsed_s else None,
        }
    return result


def report(result: dict[str, Any]) -> str:
    lines = [
        f"# Quality gate run {result['run_id']}",
        "",
        f"Started: {result['started_at']}",
        "",
        "| Scenario | Correct | Errors | p95 ms | Requests/s |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in result["summary"].items():
        lines.append(
            f"| {name} | {metrics['correct']}/{metrics['requests']} | {metrics['errors']} | {metrics['p95_ms']} | {metrics['throughput_rps']} |"
        )
    resources = result.get("resources", {})
    if resources.get("after"):
        lines += [
            "",
            f"End working set: {resources['after']['memory_working_set_bytes']} bytes; CPU used during requests: {resources['cpu_usage_core_nanoseconds_delta']} core ns.",
        ]
    if "dependency_spans" in result:
        coverage = result["trace_coverage"]
        lines += [
            "",
            f"Trace coverage: {coverage['matched']}/{coverage['requests']} requests.",
            "",
            "| Scenario | Component | Mean span time ms/request |",
            "|---|---|---:|",
        ]
        trace_spans = result["dependency_spans"]
        for name in result["summary"]:
            scenario_samples = [
                sample for sample in result["samples"] if sample["scenario_id"] == name
            ]
            components = sorted(
                {
                    span["component"]
                    for sample in scenario_samples
                    for span in trace_spans.get(sample["trace_id"], [])
                }
            )
            for component in components:
                total = sum(
                    span["duration_ms"]
                    for sample in scenario_samples
                    for span in trace_spans.get(sample["trace_id"], [])
                    if span["component"] == component
                )
                lines.append(f"| {name} | {component} | {total / len(scenario_samples):.3f} |")
        lines += ["", "Component values sum matching span durations; nested spans can overlap."]
    lines += ["", "Trace IDs for every request are in `run.json`.", ""]
    return "\n".join(lines)


def evaluate(result: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    failures = []
    for name, limits in gates.items():
        if name == "_resources":
            after = result.get("resources", {}).get("after")
            for key, bound in limits.items():
                if key not in {
                    "memory_working_set_bytes_max",
                    "cpu_usage_core_nanoseconds_delta_max",
                }:
                    raise ValueError(f"unknown resource gate {key}")
                value = (
                    result["resources"].get("cpu_usage_core_nanoseconds_delta")
                    if key.startswith("cpu_")
                    else after.get("memory_working_set_bytes")
                    if after
                    else None
                )
                if value is None or value > bound:
                    failures.append(f"resources: {key} observed={value} limit={bound}")
            continue
        metrics = result["summary"].get(name)
        if metrics is None:
            failures.append(f"{name}: scenario missing")
            continue
        for key, bound in limits.items():
            if key not in {"errors_max", "p95_ms_max", "throughput_rps_min"}:
                raise ValueError(f"unknown gate {key}")
            metric = key.removesuffix("_max").removesuffix("_min")
            value = metrics[metric]
            if (
                value is None
                or (key.endswith("_max") and value > bound)
                or (key.endswith("_min") and value < bound)
            ):
                failures.append(f"{name}: {metric}={value} violates {key}={bound}")
    return failures
