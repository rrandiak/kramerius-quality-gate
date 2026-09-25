"""Monograph structure from fetch_solr.py child-count files.

Profiles: single (pages only), multipart (monographunits, each with pages), mixed.

    uv run --with numpy calibration/monographs.py [data/raw/solr]
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np


def load(path: Path) -> dict[str, int]:
    with open(path) as f:
        return {pid: int(n) for pid, n in (line.rstrip("\n").split("\t") for line in f)}


def describe(name: str, v: np.ndarray) -> None:
    q = np.percentile(v, [1, 5, 10, 25, 50, 75, 90, 95, 99]).round(0).astype(int)
    lv = np.log(v[v > 0])
    print(f"{name}: n={v.size} mean={v.mean():.1f} p1..p99={q.tolist()} max={v.max()}"
          f" | lognorm mu={lv.mean():.2f} sigma={lv.std():.2f}"
          f" | even={np.mean(v % 2 == 0):.2f} mod4={np.mean(v % 4 == 0):.2f}")
    print(f"   top={Counter(v.tolist()).most_common(12)}")
    edges = [1, 2, 3, 5, 9, 17, 33, 65, 129, 257, 513, 1025, 1e9]
    h = np.histogram(v, edges)[0]
    print("   hist " + " ".join(f"{int(a)}-:{c}" for a, c in zip(edges, h, strict=False)))


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/solr")
    mp = load(d / "children.monograph.page.tsv")
    mu = load(d / "children.monograph.monographunit.tsv")
    up = load(d / "children.monographunit.page.tsv")
    single = [n for pid, n in mp.items() if pid not in mu]
    mixed = [pid for pid in mu if pid in mp]
    print(f"monographs with pages={len(mp)} with units={len(mu)} both={len(mixed)}")
    describe("pages per single-part monograph", np.array(single))
    describe("units per multipart monograph", np.array(list(mu.values())))
    describe("pages per monographunit", np.array(list(up.values())))
    if mixed:
        describe("direct pages of mixed monographs", np.array([mp[p] for p in mixed]))
    # within-title spread of unit sizes: needs unit->parent, not in facet files; use unit count vs total pages
    print("\npages per single monograph by decade needs dates — not fetched")


if __name__ == "__main__":
    main()
