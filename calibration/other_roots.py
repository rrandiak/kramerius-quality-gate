"""Structure signatures and child-count distributions for non-periodical, non-monograph roots.

Input: `<model path>,<pid path>` per node (all nodes, not just pages).

    uv run --with numpy calibration/other_roots.py PATHS_AND_MODELS
"""

import sys
from collections import Counter, defaultdict
from collections.abc import Iterator

import numpy as np


def _lines(path: object) -> Iterator[str]:
    """Lines of a file, closed when exhausted (dumps are too large to read at once)."""
    with open(path) as f:  # type: ignore[call-overload]
        yield from f


F = sys.argv[1]
kids = defaultdict(Counter)  # node pid path -> Counter(child model)
model = {}
roots = Counter()
for line in _lines(F):
    line = line.strip()
    if not line:
        continue
    mp, pp = line.split(",", 1)
    ms = mp.split("/")
    ps = pp.split("/")
    if len(ms) != len(ps):
        continue
    model[pp] = ms[-1]
    if len(ps) == 1:
        roots[ms[0]] += 1
    else:
        kids["/".join(ps[:-1])][ms[-1]] += 1
# per root signature: set of model paths below
sig = defaultdict(set)
for line in _lines(F):
    line = line.strip()
    if not line:
        continue
    mp, pp = line.split(",", 1)
    r = pp.split("/", 1)[0]
    parts = mp.split("/")
    if len(parts) > 1:
        sig[r].add("/".join(parts[1:]))
    else:
        sig[r]
rootmodel = {pp: mm for pp, mm in model.items() if "/" not in pp}
bysig = Counter(
    (rootmodel[r], "+".join(sorted(s)) or "(none)") for r, s in sig.items() if r in rootmodel
)
print("root model | structure signature | roots")
for (rm, s), c in bysig.most_common(40):
    print(f"  {rm:15} {s:60} {c}")
# child count distributions per (node model -> child model)
dist = defaultdict(list)
for pp, cnt in kids.items():
    for cm, c in cnt.items():
        dist[(model.get(pp, "?"), cm)].append(c)
print("\nedge  n  mean  p10 p25 p50 p75 p90 p99 max  even% top")
for (a, b), v in sorted(dist.items(), key=lambda x: -len(x[1])):
    v = np.array(v)
    if len(v) < 20:
        continue
    q = np.percentile(v, [10, 25, 50, 75, 90, 99])
    print(
        f"  {a}->{b}: {len(v)} {v.mean():.1f} {q.round(0)} {v.max()} {100 * np.mean(v % 2 == 0):.0f} {Counter(v.tolist()).most_common(6)}"
    )
