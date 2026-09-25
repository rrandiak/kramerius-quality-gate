# XML namespaces used in generated FOXML, registered once so prefixes come out readable.

import xml.etree.ElementTree as ET

FOXML = "info:fedora/fedora-system:def/foxml#"
MODS = "http://www.loc.gov/mods/v3"
DC = "http://purl.org/dc/elements/1.1/"
OAI_DC = "http://www.openarchives.org/OAI/2.0/oai_dc/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
FEDORA_MODEL = "info:fedora/fedora-system:def/model#"
KRAMERIUS = "http://www.nsdl.org/ontologies/relationships#"
OAI = "http://www.openarchives.org/OAI/2.0/"

for _prefix, _uri in {
    "foxml": FOXML,
    "mods": MODS,
    "dc": DC,
    "oai_dc": OAI_DC,
    "rdf": RDF,
    "fedora-model": FEDORA_MODEL,
    "kramerius": KRAMERIUS,
    "oai": OAI,
}.items():
    ET.register_namespace(_prefix, _uri)


def tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def sub(
    parent: ET.Element, namespace: str, name: str, text: str | None = None, **attributes: str
) -> ET.Element:
    element = ET.SubElement(parent, tag(namespace, name), attributes)
    element.text = text
    return element
