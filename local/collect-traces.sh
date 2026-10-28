#!/usr/bin/env bash
set -euo pipefail
if test "$#" -ne 1; then
  echo "usage: bash local/collect-traces.sh runs/NAME" >&2
  exit 2
fi
run_dir=$1
test -f "$run_dir/run.json"
.venv/bin/python local/extract-traces.py "$run_dir"
.venv/bin/qg traces "$run_dir/run.json" "$run_dir/traces.jsonl"
