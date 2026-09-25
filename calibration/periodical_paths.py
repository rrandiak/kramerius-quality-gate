"""Structure statistics of periodicals from a pid-paths dump.

Input: one line per page, `<periodical>/<volume>[/<item>[/<sub>]]/<page>`.
The dump carries no models, so levels are inferred from depth:
0 = periodical, 1 = volume, 2 = item (issue), 3 = sub-item (supplement...).

Pass 1 streams the file (grouped by periodical) into a compact node table.
Pass 2 prints distributions, fits and correlations, and dumps JSON.

    uv run --with numpy --with scipy calibration/periodical_paths.py PATHS [OUT.json]
"""

import json
import sys
from collections import Counter

import numpy as np
from scipy import stats

LEVELS = ["periodical", "volume", "item", "sub-item", "sub-sub"]


def read_nodes(path: str):
    """Return node columns (title, depth, direct_pages, children, subtree_pages) + page depths."""
    title_idx: dict[str, int] = {}
    cols: dict[str, list[int]] = {k: [] for k in ("title", "depth", "pages", "children", "total")}
    page_depth = Counter()
    per_title_depth: list[Counter] = []
    current: str | None = None
    nodes: dict[str, list[int]] = {}  # prefix -> [depth, direct pages, children, subtree pages]

    def flush():
        t = title_idx[current]
        for d, pages, children, total in nodes.values():
            cols["title"].append(t)
            cols["depth"].append(d)
            cols["pages"].append(pages)
            cols["children"].append(children)
            cols["total"].append(total)
        nodes.clear()

    with open(path, encoding="ascii", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("/")
            if len(parts) < 2:
                continue
            root = parts[0]
            if root != current:
                if current is not None:
                    flush()
                if root in title_idx:
                    sys.exit(f"input not grouped by periodical: {root} reappears")
                title_idx[root] = len(title_idx)
                per_title_depth.append(Counter())
                current = root
            leaf_depth = len(parts) - 1
            page_depth[leaf_depth] += 1
            per_title_depth[-1][leaf_depth] += 1
            prefix = ""
            for d in range(leaf_depth):
                prefix = parts[d] if d == 0 else prefix + "/" + parts[d]
                node = nodes.get(prefix)
                if node is None:
                    node = nodes[prefix] = [d, 0, 0, 0]
                    if d > 0:
                        nodes[prefix.rsplit("/", 1)[0]][2] += 1
                node[3] += 1
            node[1] += 1
    if current is not None:
        flush()
    arrays = {k: np.asarray(v, dtype=np.int64) for k, v in cols.items()}
    return arrays, page_depth, per_title_depth


def describe(x: np.ndarray) -> dict:
    x = x[x > 0]
    if x.size == 0:
        return {"n": 0}
    lx = np.log(x)
    q = np.percentile(x, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    mu, sigma = float(lx.mean()), float(lx.std())
    ks_ln = stats.kstest(lx, "norm", args=(mu, sigma)).statistic
    mean, var = float(x.mean()), float(x.var())
    # NegBin by moments (only meaningful if overdispersed)
    ks_nb = None
    if var > mean:
        p = mean / var
        r = mean * p / (1 - p)
        ks_nb = float(np.max(np.abs(
            np.searchsorted(np.sort(x), np.arange(x.max() + 1), side="right") / x.size
            - stats.nbinom.cdf(np.arange(x.max() + 1), r, p)
        )))
    return {
        "n": int(x.size),
        "mean": round(mean, 2),
        "cv": round(float(np.sqrt(var) / mean), 2),
        "min": int(x.min()),
        "p": dict(zip(["1", "5", "10", "25", "50", "75", "90", "95", "99"], [float(v) for v in q], strict=False)),
        "max": int(x.max()),
        "lognorm_mu": round(mu, 3),
        "lognorm_sigma": round(sigma, 3),
        "ks_lognorm": round(float(ks_ln), 3),
        "ks_negbin": None if ks_nb is None else round(ks_nb, 3),
        "top_values": Counter(x.tolist()).most_common(12),
        "frac_even": round(float(np.mean(x % 2 == 0)), 3),
        "frac_mod4": round(float(np.mean(x % 4 == 0)), 3),
    }


def icc_log(values: np.ndarray, groups: np.ndarray) -> float:
    """Share of variance of log(values) explained by the group (title)."""
    m = values > 0
    lv, g = np.log(values[m]), groups[m]
    total = lv.var()
    if total == 0:
        return 0.0
    sums = np.bincount(g, lv)
    counts = np.bincount(g)
    ok = counts > 0
    means = np.zeros_like(sums)
    means[ok] = sums[ok] / counts[ok]
    return float(means[g].var() / total)


def per_title_median(values: np.ndarray, groups: np.ndarray, n_titles: int) -> np.ndarray:
    out = np.full(n_titles, np.nan)
    order = np.argsort(groups, kind="stable")
    g, v = groups[order], values[order]
    bounds = np.flatnonzero(np.diff(g)) + 1
    for chunk_g, chunk_v in zip(np.split(g, bounds), np.split(v, bounds), strict=False):
        if chunk_v.size:
            out[chunk_g[0]] = np.median(chunk_v)
    return out


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    a, page_depth, per_title_depth = read_nodes(sys.argv[1])
    n_titles = int(a["title"].max()) + 1
    report: dict = {"titles": n_titles, "pages": int(sum(page_depth.values()))}
    report["page_depth"] = {LEVELS[d - 1] + "→page": c for d, c in sorted(page_depth.items())}

    # structural shapes: which leaf depths a title uses
    shapes = Counter(tuple(sorted(c)) for c in per_title_depth)
    report["title_shapes"] = {"/".join(map(str, k)): v for k, v in shapes.most_common(10)}

    by_depth = {}
    for d in range(4):
        m = a["depth"] == d
        if not m.any():
            continue
        ch, pg = a["children"][m], a["pages"][m]
        kinds = {
            "only_children": int(np.sum((ch > 0) & (pg == 0))),
            "only_pages": int(np.sum((ch == 0) & (pg > 0))),
            "mixed": int(np.sum((ch > 0) & (pg > 0))),
        }
        by_depth[LEVELS[d]] = {
            "nodes": int(m.sum()),
            "kinds": kinds,
            "children": describe(ch),
            "direct_pages": describe(pg),
            "subtree_pages": describe(a["total"][m]),
            "icc_children": round(icc_log(ch, a["title"][m]), 3),
            "icc_direct_pages": round(icc_log(pg, a["title"][m]), 3),
        }
    report["levels"] = by_depth

    # correlations at title level
    t = a["depth"] == 0
    vols = np.zeros(n_titles)
    vols[a["title"][t]] = a["children"][t]
    tot = np.zeros(n_titles)
    tot[a["title"][t]] = a["total"][t]
    v = (a["depth"] == 1) & (a["children"] > 0)
    items_med = per_title_median(a["children"][v], a["title"][v], n_titles)
    i = (a["depth"] == 2) & (a["pages"] > 0)
    ppi_med = per_title_median(a["pages"][i], a["title"][i], n_titles)
    ok = ~np.isnan(items_med) & ~np.isnan(ppi_med) & (vols > 0)

    def rho(x, y):
        return round(float(stats.spearmanr(x, y).statistic), 3)

    report["title_correlations"] = {
        "n": int(ok.sum()),
        "volumes~items_per_volume": rho(vols[ok], items_med[ok]),
        "volumes~pages_per_item": rho(vols[ok], ppi_med[ok]),
        "items_per_volume~pages_per_item": rho(items_med[ok], ppi_med[ok]),
    }
    report["title_median_items_per_volume_hist"] = dict(
        zip(
            ["1", "2-3", "4-5", "6-9", "10-15", "16-30", "31-60", "61-120", "121-250", "251-400", ">400"],
            np.histogram(items_med[~np.isnan(items_med)], [1, 2, 4, 6, 10, 16, 31, 61, 121, 251, 401, 1e9])[0].tolist(), strict=False,
        )
    )
    report["title_median_pages_per_item_hist"] = dict(
        zip(
            ["1-2", "3-4", "5-8", "9-12", "13-16", "17-24", "25-40", "41-80", "81-200", ">200"],
            np.histogram(ppi_med[~np.isnan(ppi_med)], [1, 3, 5, 9, 13, 17, 25, 41, 81, 201, 1e9])[0].tolist(), strict=False,
        )
    )

    # within-volume: does issue size depend on issue count?
    iv = (a["depth"] == 2) & (a["pages"] > 0)
    # parent volume of each item is not stored; approximate with title-level residuals
    resid_items = np.log(a["children"][v]) - np.log(items_med[a["title"][v]])
    report["items_per_volume_within_title_sigma"] = round(float(np.std(resid_items)), 3)
    resid_ppi = np.log(a["pages"][iv]) - np.log(ppi_med[a["title"][iv]])
    report["pages_per_item_within_title_sigma"] = round(float(np.std(resid_ppi[np.isfinite(resid_ppi)])), 3)

    out = json.dumps(report, indent=1, ensure_ascii=False, default=str)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w") as f:
            f.write(out)
    print(out)


if __name__ == "__main__":
    main()
