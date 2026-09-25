# The generated document tree: immutable nodes built bottom-up, one per Kramerius object.
#
# A node's key is its path in the corpus ("seed-1", "root", 12, "volume", 3, "issue", 7, "page", 2).
# The pid is derived from the key and every random draw for the node comes from a stream keyed by
# it, so the same node is byte-identical no matter how large the corpus around it grows.

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property

from .spec import AltoProducer

_PID_NAMESPACE = uuid.UUID("6f1c6c1e-2b4a-4d8e-9a53-0e2c5d7b8a41")


def pid_for(key: tuple[str, ...]) -> str:
    return f"uuid:{uuid.uuid5(_PID_NAMESPACE, '/'.join(key))}"


@dataclass(frozen=True)
class Scan:
    """Digitization properties shared by the pages of one document (or periodical volume)."""

    paper: str
    width: int  # pixels
    height: int
    dpi: int
    alto_version: str
    producer: AltoProducer
    has_word_confidence: bool


@dataclass(frozen=True)
class Description:
    """Descriptive values the MODS and DC builders draw from; unset fields are left out."""

    title: str | None = None
    part_number: str | None = None
    date: str | None = None
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    place: str | None = None
    language: str | None = None
    page_number: str | None = None
    page_type: str | None = None
    extent: str | None = None


@dataclass(frozen=True)
class Node:
    key: tuple[str, ...]
    model: str
    label: str
    description: Description
    licenses: tuple[str, ...] = ()
    contains_licenses: tuple[str, ...] = ()
    scan: Scan | None = None  # pages only
    profile: str | None = None  # roots only: the spec profile the document was drawn from
    children: tuple["Node", ...] = field(default_factory=tuple)

    @cached_property
    def pid(self) -> str:
        return pid_for(self.key)

    @cached_property
    def page_count(self) -> int:
        own = 1 if self.model == "page" else 0
        return own + sum(child.page_count for child in self.children)

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()


def licenses_below(children: tuple[Node, ...]) -> tuple[str, ...]:
    """Every license set anywhere under these children: what a parent's containsLicense lists."""
    found: set[str] = set()
    for child in children:
        found.update(child.licenses)
        found.update(child.contains_licenses)
    return tuple(sorted(found))
