"""Seeded, stratified pid sample for FOXML archive exports.

Covers every root model, periodical frequency profile, monograph size/license
stratum, collection depth, page type, ALTO software, plus a few complete small
trees (to verify relations end to end). Output:

  OUT/pids.txt     one pid per line (download list)
  OUT/sample.tsv   pid, model, stratum — why each pid is in the sample

    uv run calibration/sample_pids.py [--seed 1] [--out data/raw/foxml]
"""

import argparse
import json
import random
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HOST = "https://api.kramerius.mzk.cz/search/api/client/v7.0/search"
RAW = Path("data/raw")
PROFILES = [(1, 2, "annual"), (2, 4, "2-3/yr"), (4, 6, "quarterly"), (6, 10, "bimonthly"), (10, 16, "monthly"),
            (16, 31, "biweekly"), (31, 61, "weekly"), (61, 251, "several/wk"), (251, 10**9, "daily")]
PAGE_TYPES = ["NormalPage", "TitlePage", "TableOfContents", "Table", "Index", "FrontEndSheet", "FrontCover",
              "BackEndSheet", "BackCover", "Jacket", "Blank", "Advertisement", "Map", "sheetmusic"]


class Sample:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str]] = {}

    def add(self, pid: str, model: str, stratum: str) -> None:
        self.rows.setdefault(pid, (model, stratum))


def solr(params: list[tuple[str, str]]) -> dict:
    url = f"{HOST}?{urllib.parse.urlencode(params + [('wt', 'json')])}"
    with urllib.request.urlopen(url, timeout=120) as r:
        data = json.load(r)
    time.sleep(0.3)
    return data


def solr_pids(q: str, rows: int, fq: str | None = None) -> list[str]:
    p = [("q", q), ("rows", str(rows)), ("fl", "pid"), ("sort", "compositeId asc")]
    if fq:
        p.append(("fq", fq))
    return [d["pid"] for d in solr(p)["response"]["docs"]]


def monographs(s: Sample, rng: random.Random) -> None:
    pages = dict(line.rstrip().split("\t") for line in open(RAW / "solr/children.monograph.page.tsv"))
    units = dict(line.rstrip().split("\t") for line in open(RAW / "solr/children.monograph.monographunit.tsv"))
    lic = {}
    for line in open(RAW / "solr/roots.tsv"):
        pid, model, licenses, *_ = line.rstrip("\n").split("\t")
        if model == "monograph":
            lic[pid] = licenses or "(none)"
    strata = defaultdict(list)
    for pid, n in pages.items():
        if pid in units or pid not in lic:
            continue
        n = int(n)
        size = "<=16" if n <= 16 else "17-100" if n <= 100 else "101-300" if n <= 300 else "301-800" if n <= 800 else ">800"
        strata[(size, lic[pid])].append(pid)
    top_lic = [k for k, _ in Counter(lic.values()).most_common(4)]
    for (size, licenses), pids in sorted(strata.items()):
        if licenses in top_lic:
            for pid in rng.sample(sorted(pids), min(3, len(pids))):
                s.add(pid, "monograph", f"single {size} {licenses}")
    for pid in rng.sample(sorted(units), 8):
        s.add(pid, "monograph", "multipart")
        for u in solr_pids(f'own_parent.pid:"{pid}"', 2):
            s.add(u, "monographunit", "unit of multipart")
            for pg in solr_pids(f'own_parent.pid:"{u}" AND model:page', 1):
                s.add(pg, "page", "page of monographunit")
    # one page per sampled single monograph
    for pid, (_model, stratum) in list(s.rows.items()):
        if stratum.startswith("single"):
            for pg in solr_pids(f'own_parent.pid:"{pid}" AND model:page', 1):
                s.add(pg, "page", f"page of monograph {stratum.split()[1]}")
    # complete small tree: the smallest sampled single monograph
    small = [p for p, (_, st) in s.rows.items() if st.startswith("single <=16")]
    if small:
        for pg in solr_pids(f'own_parent.pid:"{small[0]}"', 100):
            s.add(pg, "page", "full tree: small monograph")


def periodicals(s: Sample, rng: random.Random, per_profile: int) -> None:
    model = dict(line.rstrip().split(",", 1) for line in open(RAW / "periodical.models.txt"))
    items: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))  # title -> volume -> items
    for line in open(RAW / "periodical.paths.txt"):
        parts = line.split("/", 3)
        if len(parts) >= 4 and model.get(parts[2]) == "periodicalitem":
            items[parts[0]][parts[1]].add(parts[2])
    profile_titles = defaultdict(list)
    for title, vols in items.items():
        counts = sorted(len(v) for v in vols.values())
        med = counts[len(counts) // 2]
        name = next(n for lo, hi, n in PROFILES if lo <= med < hi)
        profile_titles[name].append(title)
    del items
    chosen = {t: name for name, ts in profile_titles.items() for t in rng.sample(sorted(ts), min(per_profile, len(ts)))}
    tree: dict[str, dict] = {t: defaultdict(lambda: defaultdict(list)) for t in chosen}
    for line in open(RAW / "periodical.paths.txt"):
        parts = line.rstrip("\n").split("/")
        if parts[0] in tree and len(parts) >= 3:
            tree[parts[0]][parts[1]]["/".join(parts[2:-1])].append(parts[-1])
    for title, name in chosen.items():
        s.add(title, "periodical", f"profile {name}")
        vol = rng.choice(sorted(tree[title]))
        s.add(vol, model.get(vol, "?"), f"volume of {name}")
        subs = sorted(tree[title][vol])
        for sub in rng.sample(subs, min(2, len(subs))):
            for i, node in enumerate(sub.split("/") if sub else []):
                s.add(node, model.get(node, "?"), f"{'item' if i == 0 else 'sub-item'} of {name}")
            pages = tree[title][vol][sub]
            s.add(rng.choice(sorted(pages)), "page", f"page of {name}")
        # up to 2 supplements and 2 articles anywhere in that volume
        extra = sorted({n for sub in subs for n in sub.split("/") if model.get(n) in ("supplement", "article")})
        for kind in ("supplement", "article"):
            of_kind = [n for n in extra if model[n] == kind]
            for node in rng.sample(of_kind, min(2, len(of_kind))):
                s.add(node, kind, f"{kind} of {name}")
    # complete small tree: one whole issue of a weekly
    weekly = [t for t, n in chosen.items() if n == "weekly"]
    if weekly:
        t = weekly[0]
        vol = next(iter(sorted(tree[t])))
        sub = sorted(tree[t][vol])[0]
        for pg in tree[t][vol][sub]:
            s.add(pg, "page", "full tree: weekly issue")
        for node in [t, vol] + sub.split("/"):
            s.add(node, model.get(node, "?"), "full tree: weekly issue")


def other_roots(s: Sample, rng: random.Random, per_sig: int) -> None:
    nodes_by_root: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in open(RAW / "other.paths-and-models.txt"):
        line = line.strip()
        if not line:
            continue
        mp, pp = line.split(",", 1)
        nodes_by_root[pp.split("/", 1)[0]].append((mp, pp))
    by_sig = defaultdict(list)
    for root, nodes in nodes_by_root.items():
        rm = next((mp for mp, pp in nodes if "/" not in pp), None)
        if rm is None or rm in ("page", "periodicalitem", "periodicalvolume", "supplement", "internalpart", "article", "track", "monographunit"):
            continue  # orphans
        sig = "+".join(sorted({"/".join(mp.split("/")[1:]) for mp, _ in nodes if "/" in mp}))
        by_sig[(rm, sig)].append(root)
    for (rm, sig), roots in sorted(by_sig.items()):
        n = per_sig if rm != "collection" else 0
        for root in rng.sample(sorted(roots), min(n, len(roots))):
            s.add(root, rm, f"{rm} [{sig or 'no children'}]")
            inner = defaultdict(list)
            for mp, pp in nodes_by_root[root]:
                if "/" in pp:
                    inner[mp.split("/")[-1]].append((mp, pp))
            for m, lst in inner.items():
                for _mp, pp in rng.sample(sorted(lst), min(2 if m != "page" else 1, len(lst))):
                    s.add(pp.rsplit("/", 1)[-1], m, f"{m} of {rm}")
    # complete small trees: one soundrecording, one convolute, one multi-page map
    for rm, want in [("soundrecording", "page+soundunit+soundunit/track"), ("convolute", "monograph+monograph/page"),
                     ("map", "page")]:
        roots = sorted(by_sig.get((rm, want), []), key=lambda r: (len(nodes_by_root[r]) < 3, len(nodes_by_root[r])))
        if roots:
            for mp, pp in nodes_by_root[roots[0]]:
                s.add(pp.rsplit("/", 1)[-1], mp.rsplit("/", 1)[-1], f"full tree: {rm}")


def collections(s: Sample, rng: random.Random) -> None:
    rows = [line.rstrip("\n").split("\t") for line in open(RAW / "solr/collections.tsv")]
    parents = {r[0]: [p for p in r[3].split(",") if p] for r in rows}
    top = [c for c, p in parents.items() if not p]
    nested = [c for c, p in parents.items() if p]
    multi = [c for c, p in parents.items() if len(p) > 1]
    for pid in rng.sample(sorted(top), 5) + rng.sample(sorted(nested), 10) + sorted(multi)[:3]:
        s.add(pid, "collection", "collection")


def pages_by_type_and_alto(s: Sample, rng: random.Random) -> None:
    for pt in PAGE_TYPES:
        prefix = f"{rng.randrange(16**3):03x}"
        for pid in solr_pids(f"model:page AND page.type:{pt}", 2, fq=f"pid:uuid\\:{prefix}*"):
            s.add(pid, "page", f"page.type {pt}")
    for kind in ("article", "supplement", "internalpart"):
        for _ in range(3):
            prefix = f"{rng.randrange(16**2):02x}"
            for pid in solr_pids(f"model:{kind}", 2, fq=f"pid:uuid\\:{prefix}*"):
                s.add(pid, kind, f"{kind} (any parent)")
    by_sw = defaultdict(list)
    with open(RAW / "periodical.alto-software.txt") as f:
        for line in f:
            pid, _, sw = line.rstrip("\n").partition(",")
            if len(by_sw[sw]) < 2000 or rng.random() < 0.001:  # bounded pool per software
                by_sw[sw].append(pid)
    for sw, pids in sorted(by_sw.items()):
        for pid in rng.sample(pids, min(4, len(pids))):
            s.add(pid, "page", f"alto {sw}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="data/raw/foxml")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    s = Sample()
    for step in (monographs, collections, pages_by_type_and_alto):
        step(s, rng)
    periodicals(s, rng, per_profile=3)
    other_roots(s, rng, per_sig=3)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pids.txt").write_text("".join(f"{p}\n" for p in s.rows))
    (out / "sample.tsv").write_text("".join(f"{p}\t{m}\t{st}\n" for p, (m, st) in s.rows.items()))
    print(f"{len(s.rows)} pids")
    for (m), c in Counter(m for m, _ in s.rows.values()).most_common():
        print(f"  {m:15} {c}")


if __name__ == "__main__":
    main()
