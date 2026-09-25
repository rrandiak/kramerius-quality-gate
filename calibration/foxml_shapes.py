"""Shapes of FOXML archive exports: datastreams, RELS-EXT, MODS/DC structure, ALTO, images.

Keeps structure and numbers only (element paths, predicate names, sizes, counts),
never values — except for RELS-EXT predicates whose values are vocabularies
(model, license, policy) and URL hosts of external datastreams.

    uv run --with numpy --with pillow calibration/foxml_shapes.py [data/raw/foxml] [OUT.json]
"""

import base64
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image

VOCAB_PREDICATES = {"hasModel", "license", "containsLicense", "licenses", "policy", "model"}
ALTO_IDS = {"ALTO"}
IMAGE_IDS = {"IMG_FULL", "IMG_THUMB", "IMG_PREVIEW"}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def paths(el: ET.Element, prefix: str = "") -> list[str]:
    """Element paths (local names), attributes as @name, for structure templates."""
    here = f"{prefix}/{local(el.tag)}"
    out = [here] + [f"{here}/@{local(a)}" for a in el.attrib]
    for child in el:
        out += paths(child, here)
    return out


def payload(version: ET.Element) -> tuple[str, bytes | ET.Element | None, str | None]:
    """(kind, content, url) of a datastreamVersion."""
    for c in version:
        name = local(c.tag)
        if name == "xmlContent":
            return "xml", next(iter(c), None), None
        if name == "binaryContent":
            return "binary", base64.b64decode("".join(c.itertext())), None
        if name == "contentLocation":
            return "location", None, c.get("REF")
    return "empty", None, None


def alto_stats(root: ET.Element) -> dict:
    counts = Counter(local(e.tag) for e in root.iter())
    page = next((e for e in root.iter() if local(e.tag) == "Page"), None)
    unit = next((e.text for e in root.iter() if local(e.tag) == "MeasurementUnit"), None)
    sw = " ".join(
        (e.text or "").strip() for e in root.iter() if local(e.tag) in ("softwareCreator", "softwareName", "softwareVersion")
    )
    words = [len(e.get("CONTENT", "")) for e in root.iter() if local(e.tag) == "String"]
    wc = [float(e.get("WC")) for e in root.iter() if local(e.tag) == "String" and e.get("WC")]
    return {
        "unit": unit,
        "software": (sw or "").strip()[:40],
        "width": float(page.get("WIDTH", 0)) if page is not None else 0,
        "height": float(page.get("HEIGHT", 0)) if page is not None else 0,
        "blocks": counts["TextBlock"],
        "lines": counts["TextLine"],
        "strings": counts["String"],
        "illustrations": counts["Illustration"] + counts["GraphicalElement"],
        "hyp": counts["HYP"],
        "mean_word_len": float(np.mean(words)) if words else 0,
        "has_wc": bool(wc),
        "namespace": ns(root.tag),
    }


def summarize(v: list[float]) -> dict:
    a = np.asarray(v, dtype=float)
    if a.size == 0:
        return {"n": 0}
    q = np.percentile(a, [10, 50, 90])
    return {"n": int(a.size), "p10": round(q[0], 1), "p50": round(q[1], 1), "p90": round(q[2], 1), "max": round(a.max(), 1)}


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/foxml")
    out_json = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    stratum = {}
    for line in open(d / "sample.tsv"):
        pid, _model, st = line.rstrip("\n").split("\t")
        stratum[pid] = st

    per_model = defaultdict(lambda: {
        "n": 0, "file_bytes": [], "ds": Counter(), "ds_kind": Counter(), "ds_bytes": defaultdict(list),
        "ds_versions": defaultdict(list), "rels": Counter(), "rels_vocab": Counter(), "ext_hosts": Counter(),
        "mods_paths": Counter(), "dc_paths": Counter(), "alto": [], "img": defaultdict(list),
        "img_mime": Counter(), "rels_counts": defaultdict(list),
    })
    skipped = Counter()
    for f in sorted(d.glob("*.xml")):
        raw = f.read_bytes()
        if raw.startswith(b"{"):
            skipped["not found (json)"] += 1
            continue
        root = ET.fromstring(raw)
        dss = [e for e in root if local(e.tag) == "datastream"]
        model = "?"
        rels_el = None
        for ds in dss:
            if ds.get("ID") == "RELS-EXT":
                versions = [v for v in ds if local(v.tag) == "datastreamVersion"]
                kind, content, _ = payload(versions[-1])
                rels_el = content
        if rels_el is not None:
            for e in rels_el.iter():
                if local(e.tag) == "hasModel":
                    model = e.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource", "").rsplit(":", 1)[-1]
        m = per_model[model]
        m["n"] += 1
        m["file_bytes"].append(len(raw))
        for ds in dss:
            dsid = ds.get("ID")
            versions = [v for v in ds if local(v.tag) == "datastreamVersion"]
            m["ds"][dsid] += 1
            m["ds_versions"][dsid].append(len(versions))
            if not versions:
                continue
            last = versions[-1]
            kind, content, url = payload(last)
            m["ds_kind"][(dsid, ds.get("CONTROL_GROUP"), kind, last.get("MIMETYPE"))] += 1
            if kind == "binary":
                m["ds_bytes"][dsid].append(len(content))
            elif kind == "xml" and content is not None:
                m["ds_bytes"][dsid].append(len(ET.tostring(content)))
            elif kind == "location":
                host = urlparse(url).netloc or url.split("/")[0]
                m["ext_hosts"][(dsid, host)] += 1
            if dsid == "BIBLIO_MODS" and kind == "xml" and content is not None:
                m["mods_paths"].update(set(paths(content)))
            if dsid == "DC" and kind == "xml" and content is not None:
                m["dc_paths"].update(set(paths(content)))
            if dsid in ALTO_IDS and content is not None:
                try:
                    alto_root = ET.fromstring(content) if kind == "binary" else content
                    m["alto"].append(alto_stats(alto_root))
                except ET.ParseError:
                    m["alto"].append({"parse_error": True})
            if dsid in IMAGE_IDS:
                m["img_mime"][(dsid, last.get("MIMETYPE"), kind)] += 1
                if kind == "binary":
                    try:
                        with Image.open(io.BytesIO(content)) as im:
                            m["img"][dsid].append((im.width, im.height, len(content)))
                    except Exception:  # noqa: BLE001 - djvu/pdf etc.
                        m["img"][dsid].append((0, 0, len(content)))
        if rels_el is not None:
            per_pred = Counter()
            for e in rels_el.iter():
                name = local(e.tag)
                if name in ("RDF", "Description"):
                    continue
                per_pred[name] += 1
                if name in VOCAB_PREDICATES:
                    val = e.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource") or (e.text or "")
                    m["rels_vocab"][(name, re.sub(r"uuid:[0-9a-f-]+", "uuid:*", val.strip()))] += 1
            m["rels"].update(set(per_pred))
            for name, c in per_pred.items():
                m["rels_counts"][name].append(c)

    report = {"skipped": dict(skipped), "models": {}}
    for model, m in sorted(per_model.items(), key=lambda x: -x[1]["n"]):
        n = m["n"]
        r = {
            "n": n,
            "file_bytes": summarize(m["file_bytes"]),
            "datastreams": {k: round(v / n, 2) for k, v in m["ds"].most_common()},
            "datastream_kinds": [
                {"id": k[0], "control": k[1], "kind": k[2], "mime": k[3], "share": round(v / n, 2)}
                for k, v in m["ds_kind"].most_common()
            ],
            "datastream_bytes": {k: summarize(v) for k, v in m["ds_bytes"].items()},
            "datastream_versions": {k: summarize(v) for k, v in m["ds_versions"].items() if max(v) > 1},
            "external_hosts": {f"{k[0]} {k[1]}": v for k, v in m["ext_hosts"].most_common(10)},
            "rels_predicates": {k: round(v / n, 2) for k, v in m["rels"].most_common()},
            "rels_predicate_counts": {k: summarize(v) for k, v in m["rels_counts"].items() if max(v) > 1},
            "rels_vocab": {f"{k[0]}={k[1]}": v for k, v in m["rels_vocab"].most_common(25)},
            "mods_paths": {k: round(v / n, 2) for k, v in m["mods_paths"].most_common(60)},
            "dc_paths": {k: round(v / n, 2) for k, v in m["dc_paths"].most_common(30)},
            "image_mime": {f"{k[0]} {k[1]} {k[2]}": v for k, v in m["img_mime"].most_common()},
            "images": {
                k: {"width": summarize([x[0] for x in v]), "height": summarize([x[1] for x in v]),
                    "bytes": summarize([x[2] for x in v])}
                for k, v in m["img"].items()
            },
        }
        alto = [a for a in m["alto"] if not a.get("parse_error")]
        if m["alto"]:
            r["alto"] = {
                "n": len(m["alto"]),
                "parse_errors": len(m["alto"]) - len(alto),
                "units": dict(Counter(a["unit"] for a in alto)),
                "software": dict(Counter(a["software"] for a in alto).most_common(8)),
                "namespace": dict(Counter(a["namespace"] for a in alto)),
                **{k: summarize([a[k] for a in alto]) for k in
                   ("width", "height", "blocks", "lines", "strings", "illustrations", "hyp", "mean_word_len")},
                "lines_per_block": summarize([a["lines"] / a["blocks"] for a in alto if a["blocks"]]),
                "strings_per_line": summarize([a["strings"] / a["lines"] for a in alto if a["lines"]]),
                "has_wc": round(float(np.mean([a["has_wc"] for a in alto])), 2) if alto else 0,
            }
        report["models"][model] = r

    text = json.dumps(report, indent=1, ensure_ascii=False)
    if out_json:
        out_json.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
