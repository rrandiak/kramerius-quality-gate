# FOXML 1.1 for one generated object: RELS-EXT relations and the datastream envelope.
#
# Page images are external (E) by default, pointing at an IIP-style image server as production
# pages do, so ALTO (managed, M) is the main payload Akubra stores. Own-child relations follow the
# METS importer that produced most production data: supplements and articles are hasIntCompPart
# (akubra's OwnRelationsMapping says hasItem for supplements; both are own relations).

import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .alto import PageLayout, alto_xml, ocr_text
from .metadata import dc_xml, mods_xml
from .tree import Node
from .xmlns import FEDORA_MODEL, FOXML, KRAMERIUS, OAI, RDF, sub, tag

OWN_RELATIONS = {
    "page": "hasPage",
    "periodicalvolume": "hasVolume",
    "periodicalitem": "hasItem",
    "monographunit": "hasUnit",
    "supplement": "hasIntCompPart",
    "article": "hasIntCompPart",
}
IMAGE_DATASTREAMS = (
    ("IMG_FULL", "big.jpg"),
    ("IMG_PREVIEW", "preview.jpg"),
    ("IMG_THUMB", "thumb.jpg"),
)


@dataclass(frozen=True)
class InlineXml:
    id: str
    mime: str
    content: ET.Element
    format_uri: str | None = None


@dataclass(frozen=True)
class Managed:
    id: str
    mime: str
    content: bytes


@dataclass(frozen=True)
class External:
    id: str
    mime: str
    url: str


Datastream = InlineXml | Managed | External


def rels_ext_xml(node: Node, tiles_url: str | None) -> ET.Element:
    rdf = ET.Element(tag(RDF, "RDF"))
    description = sub(rdf, RDF, "Description")
    description.set(tag(RDF, "about"), f"info:fedora/{node.pid}")
    sub(description, FEDORA_MODEL, "hasModel").set(
        tag(RDF, "resource"), f"info:fedora/model:{node.model}"
    )
    sub(description, OAI, "itemID", node.pid)
    for child in node.children:
        relation = OWN_RELATIONS[child.model]
        sub(description, KRAMERIUS, relation).set(tag(RDF, "resource"), f"info:fedora/{child.pid}")
    for license_name in node.licenses:
        sub(description, KRAMERIUS, "license", license_name)
    for license_name in node.contains_licenses:
        sub(description, KRAMERIUS, "containsLicense", license_name)
    if tiles_url is not None:
        sub(description, KRAMERIUS, "tiles-url", tiles_url)
    return rdf


def datastreams(
    node: Node, layout: PageLayout | None, image_base_url: str, created: str
) -> list[Datastream]:
    uuid = node.pid.removeprefix("uuid:")
    tiles_url = f"{image_base_url.rstrip('/')}/{uuid}" if node.model == "page" else None
    streams: list[Datastream] = [
        InlineXml("DC", "text/xml", dc_xml(node), "http://www.openarchives.org/OAI/2.0/oai_dc/"),
        InlineXml("BIBLIO_MODS", "text/xml", mods_xml(node, created), "http://www.loc.gov/mods/v3"),
        InlineXml("RELS-EXT", "application/rdf+xml", rels_ext_xml(node, tiles_url),
                  "info:fedora/fedora-system:FedoraRELSExt-1.0"),
    ]  # fmt: skip
    if node.model != "page":
        return streams

    assert layout is not None and node.scan is not None  # pages always get a layout and a scan
    streams += [
        External(ds_id, "image/jpeg", f"{tiles_url}/{file}") for ds_id, file in IMAGE_DATASTREAMS
    ]
    streams.append(Managed("TEXT_OCR", "text/plain", ocr_text(layout).encode()))
    streams.append(Managed("ALTO", "text/xml", alto_xml(layout, node.scan, f"{uuid}.jp2")))
    return streams


def foxml_bytes(node: Node, streams: list[Datastream], created: str) -> bytes:
    root = ET.Element(tag(FOXML, "digitalObject"), {"VERSION": "1.1", "PID": node.pid})
    properties = sub(root, FOXML, "objectProperties")
    for name, value in (
        ("info:fedora/fedora-system:def/model#state", "Active"),
        ("info:fedora/fedora-system:def/model#label", node.label[:255]),
        ("info:fedora/fedora-system:def/model#ownerId", "fedoraAdmin"),
        ("info:fedora/fedora-system:def/model#createdDate", created),
        ("info:fedora/fedora-system:def/view#lastModifiedDate", created),
    ):
        sub(properties, FOXML, "property", NAME=name, VALUE=value)

    for stream in streams:
        control_group = (
            "X" if isinstance(stream, InlineXml) else "M" if isinstance(stream, Managed) else "E"
        )
        datastream = sub(root, FOXML, "datastream", ID=stream.id, CONTROL_GROUP=control_group,
                         STATE="A", VERSIONABLE="false")  # fmt: skip
        version = sub(datastream, FOXML, "datastreamVersion", ID=f"{stream.id}.0", LABEL="",
                      CREATED=created, MIMETYPE=stream.mime)  # fmt: skip
        match stream:
            case InlineXml(format_uri=format_uri, content=content):
                if format_uri is not None:
                    version.set("FORMAT_URI", format_uri)
                sub(version, FOXML, "xmlContent").append(content)
            case Managed(content=content):
                version.set("SIZE", str(len(content)))
                sub(version, FOXML, "binaryContent", base64.b64encode(content).decode())
            case External(url=url):
                sub(version, FOXML, "contentLocation", TYPE="URL", REF=url)
    document: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return document
