"""Fetch structure aggregates from a public Kramerius client search API.

Sequential and throttled; every file lands in OUT_DIR (data/raw/solr/).
Only pids, models, counts, licenses and collection pids — no metadata content.

  children.<parent_model>.<child_model>.tsv   <parent pid>\t<count>
      direct children per parent, via facet on own_parent.pid sliced by pid prefix
  roots.tsv   <pid>\t<model>\t<licenses,>\t<in_collections.direct,>\t<in_collections,>
      every level:0 document (cursor paged)
  collections.tsv   same columns, for model:collection at any level
  aggregates.json   facet counts: models of monograph children, where licenses and
      direct collection membership sit (by model and level)

    uv run calibration/fetch_solr.py [--host URL] [--out data/raw/solr] [--only NAME...]
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "https://api.kramerius.mzk.cz/search/api/client/v7.0/search"
PAUSE_S = 0.5
PREFIXES = "0123456789abcdef"

CHILD_EDGES = [
    ("monograph", "page"),
    ("monograph", "monographunit"),
    ("monographunit", "page"),
]
ROOT_FIELDS = ["pid", "model", "licenses.facet", "in_collections.direct", "in_collections"]


def query(host: str, params: list[tuple[str, str]], retries: int = 4) -> dict:
    url = f"{host}?{urllib.parse.urlencode(params + [('wt', 'json')])}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = json.load(r)
            time.sleep(PAUSE_S)
            return data
        except Exception as e:  # noqa: BLE001 - network: retry anything, then give up
            wait = 5 * 2**attempt
            print(f"  retry in {wait}s after {e}", file=sys.stderr)
            time.sleep(wait)
    sys.exit(f"giving up on {url}")


def facet_pairs(data: dict, field: str) -> list[tuple[str, int]]:
    flat = data["facet_counts"]["facet_fields"][field]
    return list(zip(flat[::2], flat[1::2], strict=False))


def fetch_children(host: str, out: Path, parent: str, child: str) -> None:
    target = out / f"children.{parent}.{child}.tsv"
    q = f"model:{child} AND own_parent.model:{parent}"
    expected = query(host, [("q", q), ("rows", "0")])["response"]["numFound"]
    got = parents = 0
    with open(target, "w") as f:
        slices = [f"own_parent.pid:uuid\\:{p}*" for p in PREFIXES] + ["-own_parent.pid:uuid\\:*"]
        for fq in slices:
            data = query(
                host,
                [
                    ("q", q),
                    ("fq", fq),
                    ("rows", "0"),
                    ("facet", "true"),
                    ("facet.field", "own_parent.pid"),
                    ("facet.limit", "-1"),
                    ("facet.mincount", "1"),
                ],
            )
            for pid, n in facet_pairs(data, "own_parent.pid"):
                f.write(f"{pid}\t{n}\n")
                got += n
                parents += 1
    status = "ok" if got == expected else f"MISMATCH (expected {expected})"
    print(f"{target.name}: {parents} parents, {got} children — {status}")


def fetch_cursor(host: str, target: Path, q: str) -> None:
    cursor, n = "*", 0
    with open(target, "w") as f:
        while True:
            data = query(
                host,
                [
                    ("q", q),
                    ("rows", "5000"),
                    ("fl", ",".join(ROOT_FIELDS)),
                    ("sort", "compositeId asc"),
                    ("cursorMark", cursor),
                ],
            )
            for d in data["response"]["docs"]:
                row = [d.get(k, "") for k in ROOT_FIELDS]
                f.write("\t".join(",".join(v) if isinstance(v, list) else v for v in row) + "\n")
                n += 1
            nxt = data["nextCursorMark"]
            print(f"  {target.name}: {n}/{data['response']['numFound']}", file=sys.stderr)
            if nxt == cursor:
                break
            cursor = nxt
    print(f"{target.name}: {n} docs")


def fetch_aggregates(host: str, out: Path) -> None:
    def facet(q: str, field: str, fq: str | None = None) -> dict:
        params = [
            ("q", q),
            ("rows", "0"),
            ("facet", "true"),
            ("facet.field", field),
            ("facet.limit", "-1"),
        ]
        if fq:
            params.append(("fq", fq))
        return dict(facet_pairs(query(host, params), field))

    agg = {
        "monograph_children_models": facet("own_parent.model:monograph", "model"),
        "monographunit_children_models": facet("own_parent.model:monographunit", "model"),
        "direct_collection_members_by_model": facet("in_collections.direct:*", "model"),
        "licenses_by_level": {
            str(lv): facet(f"level:{lv}", "licenses.facet") for lv in range(0, 5)
        },
        "docs_with_own_license_by_model": facet("licenses.facet:*", "model"),
        "docs_by_model": facet("*:*", "model"),
    }
    (out / "aggregates.json").write_text(json.dumps(agg, indent=1))
    print("aggregates.json written")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--out", default="data/raw/solr")
    ap.add_argument("--only", nargs="*", help="children aggregates roots collections")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = set(a.only or ["children", "aggregates", "roots", "collections"])
    if "children" in todo:
        for parent, child in CHILD_EDGES:
            fetch_children(a.host, out, parent, child)
    if "aggregates" in todo:
        fetch_aggregates(a.host, out)
    if "collections" in todo:
        fetch_cursor(a.host, out / "collections.tsv", "model:collection")
    if "roots" in todo:
        fetch_cursor(a.host, out / "roots.tsv", "level:0")


if __name__ == "__main__":
    main()
