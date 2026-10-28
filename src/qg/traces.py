"""Join OTLP JSON file-exporter spans to HTTP samples by W3C trace ID."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .benchmark import report


def _attributes(items: list[dict[str, Any]]) -> dict[str, str]:
    return {item["key"]: str(next(iter(item.get("value", {}).values()), "")) for item in items}


def _component(span: dict[str, Any], resource: dict[str, str]) -> str:
    attrs = _attributes(span.get("attributes", []))
    db = attrs.get("db.system", attrs.get("db.system.name", ""))
    if "postgres" in db:
        return "postgresql"
    if "solr" in attrs.get("server.address", "") or "solr" in attrs.get("url.full", ""):
        return "solr"
    if "qg-images" in attrs.get("server.address", "") or "qg-images" in attrs.get("url.full", ""):
        return "images"
    if attrs.get("http.request.method") and str(span.get("kind")) in {"SPAN_KIND_CLIENT", "3"}:
        return "http_other"
    return resource.get("service.name", "application")


def attach(run_path: Path, traces_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(run_path.read_text())
    wanted = {sample["trace_id"] for sample in result["samples"]}
    spans: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in traces_path.read_text().splitlines():
        if not line.strip():
            continue
        batch = json.loads(line)
        for resource_spans in batch.get("resourceSpans", []):
            resource = _attributes(resource_spans.get("resource", {}).get("attributes", []))
            for scope in resource_spans.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    trace_id = span.get("traceId", "").lower()
                    if trace_id in wanted:
                        duration_ms = (
                            int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])
                        ) / 1_000_000
                        spans[trace_id].append(
                            {
                                "span_id": span.get("spanId"),
                                "parent_span_id": span.get("parentSpanId"),
                                "name": span.get("name"),
                                "component": _component(span, resource),
                                "duration_ms": round(duration_ms, 3),
                            }
                        )
    result["trace_coverage"] = {"matched": len(spans), "requests": len(wanted)}
    result["dependency_spans"] = spans
    run_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (run_path.parent / "report.md").write_text(report(result))
    return result
