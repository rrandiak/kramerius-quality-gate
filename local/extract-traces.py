"""Save only collector spans belonging to one local benchmark run."""

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python local/extract-traces.py runs/NAME")
    run_dir = Path(sys.argv[1])
    run = json.loads((run_dir / "run.json").read_text())
    wanted = {sample["trace_id"] for sample in run["samples"]}
    output = run_dir / "traces.jsonl"
    temporary = run_dir / "traces.jsonl.tmp"

    command = ["docker", "exec", "k3d-qg-server-0", "cat", "/qg/traces/traces.jsonl"]
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is not None
        with temporary.open("w") as target:
            for line in proc.stdout:
                batch = json.loads(line)
                matched_resources = []
                for resource in batch.get("resourceSpans", []):
                    scopes = []
                    for scope in resource.get("scopeSpans", []):
                        spans = [
                            span
                            for span in scope.get("spans", [])
                            if span.get("traceId", "").lower() in wanted
                        ]
                        if spans:
                            scopes.append({**scope, "spans": spans})
                    if scopes:
                        matched_resources.append({**resource, "scopeSpans": scopes})
                if matched_resources:
                    target.write(json.dumps({"resourceSpans": matched_resources}) + "\n")
        if proc.wait() != 0:
            raise RuntimeError(proc.stderr.read().strip())
    temporary.replace(output)


if __name__ == "__main__":
    main()
