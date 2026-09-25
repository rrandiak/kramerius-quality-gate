"""Licenses and collection membership from fetch_solr.py roots.tsv / collections.tsv.

    uv run --with numpy calibration/roots.py [data/raw/solr]
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def rows(path: Path):
    with open(path) as f:
        for line in f:
            pid, model, lic, direct, trans = (line.rstrip("\n").split("\t") + [""] * 5)[:5]
            yield pid, model, set(filter(None, lic.split(","))), [c for c in direct.split(",") if c], [
                c for c in trans.split(",") if c
            ]


def pct(v: np.ndarray, qs=(50, 75, 90, 95, 99)) -> str:
    return " ".join(f"p{q}={np.percentile(v, q):.0f}" for q in qs) + f" max={v.max()}"


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/solr")
    roots = list(rows(d / "roots.tsv"))
    colls = {r[0]: r for r in rows(d / "collections.tsv")}

    by_model = Counter(r[1] for r in roots)
    print("roots by model:", dict(by_model.most_common()))

    print("\n== licenses (set per root, as indexed) by root model")
    combos = defaultdict(Counter)
    for _, model, lic, _, _ in roots:
        combos[model]["+".join(sorted(lic)) or "(none)"] += 1
    for model, n in by_model.most_common(12):
        top = ", ".join(f"{k} {100 * v / n:.1f}%" for k, v in combos[model].most_common(6))
        print(f"  {model:15} {top}")

    print("\n== collection membership (direct) of roots")
    members = Counter()
    per_doc = defaultdict(list)
    for _pid, model, _, direct, _ in roots:
        if model == "collection":
            continue
        per_doc[model].append(len(direct))
        for c in direct:
            members[c] += 1
    for model, _n in by_model.most_common(10):
        if model == "collection":
            continue
        v = np.array(per_doc[model])
        print(f"  {model:15} in>=1: {100 * np.mean(v > 0):5.1f}%  of those: mean {v[v > 0].mean() if (v > 0).any() else 0:.2f}"
              f"  dist {Counter(v[v > 0].tolist()).most_common(5)}")
    m = np.array([members.get(c, 0) for c in colls])
    print(f"  root members per collection: {pct(m)}  empty={int(np.sum(m == 0))}/{m.size}")
    lm = np.log(m[m > 0])
    print(f"  lognormal fit on non-empty: mu={lm.mean():.2f} sigma={lm.std():.2f}")

    print("\n== collection nesting")
    parents = np.array([len(r[3]) for r in colls.values()])
    print(f"  collections with a parent collection: {np.mean(parents > 0):.2f}, parents dist {Counter(parents.tolist()).most_common(5)}")
    child_colls = Counter(p for r in colls.values() for p in r[3])
    cc = np.array([child_colls.get(c, 0) for c in colls])
    print(f"  sub-collections per collection: non-zero {np.sum(cc > 0)}  {pct(cc)}")

    def depth(c: str, seen=()) -> int:
        ps = [p for p in colls.get(c, (None, None, None, [], []))[3] if p in colls and p not in seen]
        return 0 if not ps else 1 + max(depth(p, seen + (c,)) for p in ps)

    print(f"  depth dist {sorted(Counter(depth(c) for c in colls).items())}")
    leaf_only = sum(1 for c in colls if members.get(c, 0) and not child_colls.get(c))
    inner_only = sum(1 for c in colls if not members.get(c, 0) and child_colls.get(c))
    both = sum(1 for c in colls if members.get(c, 0) and child_colls.get(c))
    print(f"  docs only={leaf_only} sub-collections only={inner_only} both={both}")


if __name__ == "__main__":
    main()
