"""Join periodical pid_paths with models into a node table (.npz).

Inputs
  PATHS   one line per page: `<periodical>/<volume>[/...]/<page>` (pids)
  MODELS  `<pid>,<model>` for every non-page pid in PATHS

Output (.npz), one row per non-page node:
  title     periodical index (order of first appearance)
  depth     0 = root
  model     index into `models`
  parent    row index of parent node (-1 for root)
  pages     direct page children
  children  direct non-page children

    uv run --with numpy calibration/periodical_tree.py PATHS MODELS OUT.npz
"""

import sys

import numpy as np


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    paths, models_file, out = sys.argv[1:]

    model_names: list[str] = []
    model_idx: dict[str, int] = {}
    pid_model: dict[str, int] = {}
    with open(models_file) as f:
        for line in f:
            pid, _, model = line.strip().partition(",")
            if not model:
                continue
            m = model_idx.setdefault(model, len(model_names))
            if m == len(model_names):
                model_names.append(model)
            pid_model[pid] = m
    unknown = model_idx.setdefault("?", len(model_names))
    if unknown == len(model_names):
        model_names.append("?")

    row: dict[str, int] = {}  # node path -> row
    title, depth, model, parent, pages, children = [], [], [], [], [], []
    titles: dict[str, int] = {}
    current = None
    with open(paths, encoding="ascii", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("/")
            if len(parts) < 2:
                continue
            if parts[0] != current:
                current = parts[0]
                row.clear()  # input is grouped by periodical (checked by periodical_paths.py)
                titles.setdefault(current, len(titles))
            t = titles[current]
            prefix = ""
            parent_row = -1
            for d in range(len(parts) - 1):
                prefix = parts[d] if d == 0 else f"{prefix}/{parts[d]}"
                r = row.get(prefix)
                if r is None:
                    r = row[prefix] = len(title)
                    title.append(t)
                    depth.append(d)
                    model.append(pid_model.get(parts[d], unknown))
                    parent.append(parent_row)
                    pages.append(0)
                    children.append(0)
                    if parent_row >= 0:
                        children[parent_row] += 1
                parent_row = r
            pages[parent_row] += 1

    np.savez_compressed(
        out,
        title=np.asarray(title, np.int32),
        depth=np.asarray(depth, np.int8),
        model=np.asarray(model, np.int8),
        parent=np.asarray(parent, np.int32),
        pages=np.asarray(pages, np.int32),
        children=np.asarray(children, np.int32),
        models=np.asarray(model_names),
        n_models_listed=len(pid_model),
    )
    known = np.asarray(model) != unknown
    print(f"titles={len(titles)} nodes={len(title)} unknown_model={int((~known).sum())}")


if __name__ == "__main__":
    main()
