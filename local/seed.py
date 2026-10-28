"""Generate and submit one versioned local FOXML corpus."""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from qg_token import get_token

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> None:
    subprocess.run(args, check=True)


def process_status(base_url: str, process_id: str, token: str) -> tuple[dict, str]:
    url = base_url + f"/search/api/admin/v7.0/processes/by_process_uuid/{process_id}"

    def read(current_token: str) -> dict:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {current_token}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    try:
        return read(token), token
    except urllib.error.HTTPError as error:
        if error.code not in {401, 403}:
            raise
        refreshed = get_token()
        return read(refreshed), refreshed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=("small", "medium", "large"), default="small")
    parser.add_argument("--pages", type=int)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--token", default=os.environ.get("QG_TOKEN", ""))
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--wait-seconds", type=int, default=600)
    parser.add_argument(
        "--resume", action="store_true", help="Wait for a previously scheduled import."
    )
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("only the local port-forward URL is accepted")
    if not args.token:
        parser.error("QG_TOKEN is required for the local admin import API")
    pages = args.pages or {"small": 24, "medium": 1000, "large": 10000}[args.tier]
    if pages < 1:
        parser.error("pages must be positive")
    spec = yaml.safe_load((ROOT / "specs/tiny.yaml").read_text())
    spec["images"]["base_url"] = "http://qg-images:8080/qg"
    spec["models"]["monograph"]["licenses"] = {"public": 1.0}
    spec["models"]["periodical"]["licenses"] = {"public": 1.0}
    corpus = ROOT / "corpora" / f"tiny-local-v1-s{args.seed}-p{pages}"
    if not corpus.exists():
        corpus.mkdir(parents=True)
        spec_path = corpus / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(spec, sort_keys=True))
        command(
            sys.executable,
            "-m",
            "qg",
            "gen",
            "--spec",
            str(spec_path),
            "--seed",
            str(args.seed),
            "--pages",
            str(pages),
            "--out",
            str(corpus / "data"),
        )
    data = corpus / "data"
    if not (data / "corpus.json").exists():
        raise RuntimeError("generation did not produce corpus.json")
    import_file = corpus / "import.json"
    if args.resume:
        if not import_file.exists():
            parser.error(f"no scheduled import in {import_file}")
        submission = json.loads(import_file.read_text())
        scheduled = submission["response"]
    else:
        remote = f"/data/import/seed/{corpus.name}"
        command(
            "kubectl",
            "--kubeconfig",
            str(ROOT / ".build-qg/kubeconfig-qg.yaml"),
            "--context",
            "k3d-qg",
            "-n",
            "qg",
            "exec",
            "worker-curator-0",
            "--",
            "mkdir",
            "-p",
            remote,
        )
        command(
            "kubectl",
            "--kubeconfig",
            str(ROOT / ".build-qg/kubeconfig-qg.yaml"),
            "--context",
            "k3d-qg",
            "-n",
            "qg",
            "cp",
            str(data / "foxml"),
            f"worker-curator-0:{remote}",
        )
        payload = json.dumps(
            {
                "defid": "import",
                "params": {
                    "inputDataDir": f"{remote}/foxml",
                    "pathtype": "absolute",
                    "startIndexer": True,
                },
            }
        ).encode()
        request = urllib.request.Request(
            args.base_url + "/search/api/admin/v7.0/processes",
            data=payload,
            headers={"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                scheduled = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"import scheduling failed: HTTP {error.code}: {error.read()[:500]!r}"
            ) from error
        submission = {"submitted_at": time.time(), "response": scheduled}
        import_file.write_text(json.dumps(submission, indent=2))
    process_id = scheduled.get("uuid")
    if not process_id:
        raise RuntimeError(f"import response has no process UUID: {scheduled}")
    deadline = time.monotonic() + args.wait_seconds
    last = None
    token = args.token
    while time.monotonic() < deadline:
        last, token = process_status(args.base_url, process_id, token)
        state = str(last.get("process", {}).get("state", "")).upper()
        batch_state = str(last.get("batch", {}).get("state", "")).upper()
        failed = {"FAILED", "ERROR", "KILLED", "CANCELLED", "WARNING"}
        finished = {"FINISHED", "COMPLETED", "DONE"}
        if state in failed or batch_state in failed:
            raise RuntimeError(f"import failed: {last}")
        if state in finished and batch_state in finished:
            break
        time.sleep(5)
    else:
        raise TimeoutError(f"import did not finish within {args.wait_seconds}s: {last}")
    import_file.write_text(json.dumps({**submission, "final": last}, indent=2))
    print(json.dumps({"corpus": str(data), "import": scheduled}, indent=2))


if __name__ == "__main__":
    main()
