# BIBLIO_MODS and DC for generated objects, shaped per model like production records.
#
# The element sets follow the per-model MODS/DC paths measured in data/derived/foxml_shapes.json:
# pages carry a minimal part/detail record, issues and volumes a partNumber + date, monographs a
# full catalog record. Values are synthetic; codes (sigla, authorities) are fixed placeholders.

import xml.etree.ElementTree as ET

from .tree import Node
from .xmlns import DC, MODS, OAI_DC, sub, tag

_PHYSICAL_LOCATION = "QGA001"  # synthetic library siglum
_RECORD_SOURCE = "QGA001"
_GENRES = {
    "monograph": "book",
    "monographunit": "volume",
    "periodical": "title",
    "periodicalvolume": "volume",
    "periodicalitem": "issue",
    "supplement": "supplement",
    "article": "article",
}


def _uuid(node: Node) -> str:
    return node.pid.removeprefix("uuid:")


def mods_xml(node: Node, created: str) -> ET.Element:
    collection = ET.Element(tag(MODS, "modsCollection"))
    mods = sub(collection, MODS, "mods", version="3.6", ID=f"MODS_{node.model.upper()}_0001")
    description = node.description

    if node.model == "page":
        part = sub(mods, MODS, "part", type=description.page_type or "NormalPage")
        sub(sub(part, MODS, "detail", type="pageNumber"), MODS, "number", description.page_number)
        sub(mods, MODS, "identifier", _uuid(node), type="uuid")
        sub(mods, MODS, "typeOfResource", "text")
        return collection

    title_info = sub(mods, MODS, "titleInfo")
    if description.title is not None:
        sub(title_info, MODS, "title", description.title)
    if description.part_number is not None:
        sub(title_info, MODS, "partNumber", description.part_number)
    for author in description.authors:
        name = sub(mods, MODS, "name", type="personal")
        sub(name, MODS, "namePart", author)
        sub(sub(name, MODS, "role"), MODS, "roleTerm", "cre", authority="marcrelator", type="code")
    sub(mods, MODS, "genre", _GENRES.get(node.model, node.model))

    origin = sub(mods, MODS, "originInfo")
    if description.place is not None:
        sub(sub(origin, MODS, "place"), MODS, "placeTerm", description.place, type="text")
    if description.publisher is not None:
        sub(origin, MODS, "publisher", description.publisher)
    if description.date is not None:
        sub(origin, MODS, "dateIssued", description.date)
    if node.model == "monograph":
        sub(origin, MODS, "issuance", "monographic")

    if description.language is not None:
        language = sub(mods, MODS, "language")
        sub(
            language, MODS, "languageTerm", description.language, authority="iso639-2b", type="code"
        )
    if description.extent is not None:
        physical = sub(mods, MODS, "physicalDescription")
        sub(physical, MODS, "form", "print", authority="marcform")
        sub(physical, MODS, "extent", description.extent)
    if node.model == "periodicalvolume" and description.date is not None:
        sub(sub(mods, MODS, "part"), MODS, "date", description.date)
    if node.model in ("monograph", "periodical", "periodicalitem"):
        location = sub(mods, MODS, "location")
        sub(location, MODS, "physicalLocation", _PHYSICAL_LOCATION, authority="siglaADR")
        sub(location, MODS, "shelfLocator", f"QG-{_uuid(node)[:8].upper()}")
    if node.model in ("monograph", "periodical"):
        _record_info(mods, node, created)
    sub(mods, MODS, "identifier", _uuid(node), type="uuid")
    return collection


def _record_info(mods: ET.Element, node: Node, created: str) -> None:
    record = sub(mods, MODS, "recordInfo")
    sub(record, MODS, "recordContentSource", _RECORD_SOURCE, authority="marcorg")
    sub(record, MODS, "recordCreationDate", created[:10].replace("-", "")[2:], encoding="marc")
    sub(record, MODS, "recordChangeDate", created, encoding="iso8601")
    sub(record, MODS, "recordIdentifier", _uuid(node), source=_RECORD_SOURCE)
    sub(record, MODS, "recordOrigin", "machine generated")
    languages = sub(record, MODS, "languageOfCataloging")
    sub(languages, MODS, "languageTerm", "cze", authority="iso639-2b")


def dc_xml(node: Node) -> ET.Element:
    root = ET.Element(tag(OAI_DC, "dc"))
    description = node.description
    sub(root, DC, "title", description.title or description.part_number or node.label)
    for author in description.authors:
        sub(root, DC, "creator", author)
    if description.publisher is not None:
        sub(root, DC, "publisher", description.publisher)
    if description.date is not None:
        sub(root, DC, "date", description.date)
    if description.language is not None:
        sub(root, DC, "language", description.language)
    sub(root, DC, "identifier", node.pid)
    sub(root, DC, "type", f"model:{node.model}")
    return root
