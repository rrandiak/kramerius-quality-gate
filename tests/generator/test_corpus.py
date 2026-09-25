# Generated corpora: reproducible, prefix-stable, structurally valid Kramerius FOXML.

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from qg.generator.alto import ALTO_NAMESPACES
from qg.generator.corpus import CorpusExistsError
from qg.generator.spec import Spec

from .conftest import datastream, generate, object_files

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
KRAMERIUS = "{http://www.nsdl.org/ontologies/relationships#}"


def _digests(corpus: Path) -> dict[str, str]:
    return {
        str(path.relative_to(corpus)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(corpus.rglob("*"))
        if path.is_file()
    }


def _manifest(corpus: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (corpus / "manifest.jsonl").read_text().splitlines()]


def _rels(foxml: Path) -> ET.Element:
    rels = datastream(foxml, "RELS-EXT")
    assert isinstance(rels, ET.Element)
    return rels


def _texts(rels: ET.Element, name: str) -> set[str]:
    return {element.text or "" for element in rels.iter(f"{KRAMERIUS}{name}")}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory, tiny_spec: Spec) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(tiny_spec, out, pages=400)
    return out


def test_same_spec_and_seed_give_identical_bytes(tmp_path: Path, tiny_spec: Spec) -> None:
    generate(tiny_spec, tmp_path / "a", pages=150)
    generate(tiny_spec, tmp_path / "b", pages=150)

    assert _digests(tmp_path / "a") == _digests(tmp_path / "b")


def test_different_seeds_give_different_pids(tmp_path: Path, tiny_spec: Spec) -> None:
    generate(tiny_spec, tmp_path / "a", pages=100, seed=1)
    generate(tiny_spec, tmp_path / "b", pages=100, seed=2)

    assert not set(object_files(tmp_path / "a")) & set(object_files(tmp_path / "b"))


def test_small_corpus_is_a_prefix_of_a_large_one(
    tmp_path: Path, corpus: Path, tiny_spec: Spec
) -> None:
    small = tmp_path / "small"
    generate(tiny_spec, small, pages=150)
    small_files, large_files = object_files(small), object_files(corpus)
    truncated = set(json.loads((small / "corpus.json").read_text())["truncated"])

    differing = {
        pid
        for pid, path in small_files.items()
        if path.read_bytes() != large_files[pid].read_bytes()
    }

    assert set(small_files) <= set(large_files)
    # only volumes/titles still open at the page budget list fewer children than in the large one
    assert differing <= truncated


def test_page_budget_is_met_and_counted(corpus: Path) -> None:
    summary = json.loads((corpus / "corpus.json").read_text())
    pages = [row for row in _manifest(corpus) if row["model"] == "page"]

    assert summary["pages"] >= summary["pages_requested"]
    assert len(pages) == summary["pages"] == summary["objects"]["page"]


def test_page_mix_follows_spec_page_shares(corpus: Path, tiny_spec: Spec) -> None:
    rows = _manifest(corpus)
    root_model = {row["pid"]: row["model"] for row in rows if row["parent"] is None}
    pages = [row for row in rows if row["model"] == "page"]
    periodical = sum(1 for row in pages if root_model[row["root"]] == "periodical")
    shares = tiny_spec.models.page_shares()

    expected = shares["periodical"] / sum(shares.values())

    assert periodical / len(pages) == pytest.approx(expected, abs=0.1)


def test_every_object_except_roots_has_exactly_one_parent(corpus: Path) -> None:
    files = object_files(corpus)
    references: dict[str, int] = {}
    for path in files.values():
        for element in _rels(path).iter():
            resource = element.get(f"{RDF}resource", "")
            if resource.startswith("info:fedora/uuid:"):
                pid = resource.removeprefix("info:fedora/")
                references[pid] = references.get(pid, 0) + 1
    roots = {str(row["pid"]) for row in _manifest(corpus) if row["parent"] is None}

    assert set(references) == set(files) - roots
    assert set(references.values()) == {1}


def test_licenses_sit_where_they_are_set(corpus: Path) -> None:
    files = object_files(corpus)
    rows = {str(row["pid"]): row for row in _manifest(corpus)}
    children: dict[str, list[str]] = {}
    for pid, row in rows.items():
        if row["parent"] is not None:
            children.setdefault(str(row["parent"]), []).append(pid)

    for pid, row in rows.items():
        rels = _rels(files[pid])
        own, contained = _texts(rels, "license"), _texts(rels, "containsLicense")
        if row["model"] in ("page", "periodicalitem", "supplement", "article"):
            assert not own and not contained, pid
        if row["model"] == "periodicalvolume":
            assert own, pid
        if row["model"] == "periodical":
            below = set().union(*(_texts(_rels(files[v]), "license") for v in children[pid]))
            assert contained == below and not own, pid
        if row["model"] == "monograph":
            assert bool(own) != bool(contained), pid  # single: license; multipart: containsLicense


def test_ocr_is_the_alto_text_and_alto_names_its_producer(corpus: Path) -> None:
    pages = [pid for pid, path in object_files(corpus).items() if datastream(path, "ALTO")]

    for pid in pages[:60]:
        path = object_files(corpus)[pid]
        alto_bytes, ocr_bytes = datastream(path, "ALTO"), datastream(path, "TEXT_OCR")
        assert isinstance(alto_bytes, bytes) and isinstance(ocr_bytes, bytes)
        alto = ET.fromstring(alto_bytes)
        namespace = alto.tag[1:].split("}")[0]
        words = [s.get("CONTENT") for s in alto.iter(f"{{{namespace}}}String")]
        software = alto.find(f".//{{{namespace}}}softwareName")

        assert namespace in ALTO_NAMESPACES.values()
        assert software is not None and software.text
        assert ocr_bytes.decode().split() == words


def test_page_images_are_external_image_server_urls(corpus: Path, tiny_spec: Spec) -> None:
    page = next(p for p in object_files(corpus).values() if datastream(p, "ALTO"))

    full = datastream(page, "IMG_FULL")

    assert isinstance(full, str)
    assert full.startswith(tiny_spec.images.base_url) and full.endswith("/big.jpg")


def test_existing_output_is_never_overwritten(corpus: Path, tiny_spec: Spec) -> None:
    with pytest.raises(CorpusExistsError):
        generate(tiny_spec, corpus, pages=10)
