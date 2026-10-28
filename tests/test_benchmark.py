import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qg.benchmark import evaluate, run
from qg.traces import attach


def test_local_run_records_correctness_and_trace_ids(tmp_path):
    pid = "uuid:11111111-1111-1111-1111-111111111111"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "corpus.json").write_text(json.dumps({"pages": 1, "seed": 1}))
    (corpus / "manifest.jsonl").write_text(
        json.dumps({"pid": pid, "model": "monograph", "parent": None})
        + "\n"
        + json.dumps({"pid": pid, "model": "page", "parent": pid})
        + "\n"
    )
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers["traceparent"])
            if "/search?" in self.path:
                body = json.dumps({"response": {"numFound": 1, "docs": [{"pid": pid}]}}).encode()
                content_type = "application/json"
            else:
                body, content_type = b"\xff\xd8\xfffixture", "image/jpeg"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = run(
            corpus,
            f"http://127.0.0.1:{server.server_port}",
            tmp_path / "run",
            iterations=2,
            concurrency=2,
            cache_state="warm",
            scenarios=["search", "thumb"],
            timeout=2,
        )
    finally:
        server.shutdown()
        worker.join()
    assert len(seen) == 4
    assert all(value.startswith("00-") and value.endswith("-01") for value in seen)
    assert result["summary"]["search"]["correct"] == 2
    assert result["summary"]["thumb"]["correct"] == 2
    assert json.loads((tmp_path / "run" / "run.json").read_text())["run_id"] == result["run_id"]
    assert evaluate(result, {"search": {"errors_max": 0}}) == []
    assert evaluate(result, {"search": {"p95_ms_max": 0}})


def test_runner_rejects_nonlocal_target(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        run(
            tmp_path,
            "https://api.kramerius.mzk.cz",
            tmp_path / "out",
            iterations=1,
            concurrency=1,
            cache_state="warm",
            scenarios=["search"],
            timeout=1,
        )


def test_trace_join_keeps_only_run_trace_ids(tmp_path):
    trace_id = "1" * 32
    run_file = tmp_path / "run.json"
    run_file.write_text(
        json.dumps(
            {
                "run_id": "run1",
                "started_at": "2026-01-01",
                "fingerprint": {},
                "summary": {
                    "search": {
                        "requests": 1,
                        "correct": 1,
                        "errors": 0,
                        "p95_ms": 5,
                        "throughput_rps": 1,
                    }
                },
                "samples": [{"scenario_id": "search", "trace_id": trace_id}],
            }
        )
    )
    spans_file = tmp_path / "spans.jsonl"
    spans_file.write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {
                                    "key": "service.name",
                                    "value": {"stringValue": "kramerius-public"},
                                }
                            ]
                        },
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "traceId": trace_id,
                                        "spanId": "2" * 16,
                                        "name": "GET",
                                        "startTimeUnixNano": "1000000",
                                        "endTimeUnixNano": "3000000",
                                        "attributes": [
                                            {
                                                "key": "server.address",
                                                "value": {"stringValue": "qg-solr"},
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        )
    )
    result = attach(run_file, spans_file)
    assert result["trace_coverage"] == {"matched": 1, "requests": 1}
    assert result["dependency_spans"][trace_id][0]["component"] == "solr"
    assert "solr" in (tmp_path / "report.md").read_text()
