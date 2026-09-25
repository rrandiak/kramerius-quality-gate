# Shared fixtures for generator tests: specs from specs/, corpora built in tmp dirs.

import base64
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from qg.generator.corpus import CorpusOptions, CorpusSummary, write_corpus
from qg.generator.spec import Spec, load_spec

SPECS = Path(__file__).resolve().parents[2] / "specs"
FOXML_NS = "{info:fedora/fedora-system:def/foxml#}"


@pytest.fixture(scope="session")
def tiny_spec() -> Spec:
    return load_spec(SPECS / "tiny.yaml")


def generate(spec: Spec, out: Path, *, pages: int, seed: int = 1) -> CorpusSummary:
    options = CorpusOptions(seed=seed, pages=pages, created="2026-01-01T00:00:00.000Z")
    return write_corpus(spec, options, out)


def object_files(corpus: Path) -> dict[str, Path]:
    """pid -> FOXML path for every object in a generated corpus."""
    return {f"uuid:{path.stem}": path for path in (corpus / "foxml").rglob("*.xml")}


def datastream(foxml: Path, datastream_id: str) -> ET.Element | bytes | str | None:
    """Content of a datastream: XML element (X), decoded bytes (M) or URL (E)."""
    root = ET.parse(foxml).getroot()
    for stream in root.iter(f"{FOXML_NS}datastream"):
        if stream.get("ID") != datastream_id:
            continue
        version = stream.find(f"{FOXML_NS}datastreamVersion")
        assert version is not None
        xml_content = version.find(f"{FOXML_NS}xmlContent")
        if xml_content is not None:
            return xml_content[0]
        binary = version.find(f"{FOXML_NS}binaryContent")
        if binary is not None:
            return base64.b64decode(binary.text or "")
        location = version.find(f"{FOXML_NS}contentLocation")
        return location.get("REF") if location is not None else None
    return None
