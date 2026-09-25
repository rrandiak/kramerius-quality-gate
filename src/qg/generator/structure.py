# Structure builders: turn a spec's profiles into document trees (monographs and periodicals).
#
# Licenses follow production FOXML (calibration/findings.md): `license` sits where it is set
# (monograph root, each monograph unit, each periodical volume) and ancestors list what is below
# them in `containsLicense`. Pages carry none.

import dataclasses
import datetime
from dataclasses import dataclass

from .distributions import Count
from .sampling import Rng
from .spec import (
    PAPER_SIZES_MM,
    MonographMultipart,
    MonographSingle,
    PagesSpec,
    PeriodicalProfile,
    PeriodicalSpec,
    Spec,
)
from .text import ZipfPool, build_names, build_places, build_publishers, build_vocabulary, title
from .tree import Description, Node, Scan, licenses_below, pid_for

_MM_PER_INCH = 25.4
_PAGE_TYPE_NORMAL = "NormalPage"


@dataclass(frozen=True)
class Pools:
    """Corpus-wide word and name pools, built once per (spec, seed)."""

    vocabulary: ZipfPool
    authors: ZipfPool
    publishers: ZipfPool
    places: ZipfPool

    @classmethod
    def build(cls, spec: Spec, rng: Rng) -> "Pools":
        metadata = spec.metadata
        return cls(
            vocabulary=build_vocabulary(
                rng.derive("vocabulary"), spec.text.vocabulary_size, spec.text.zipf_exponent
            ),
            authors=build_names(rng.derive("authors"), metadata.authors, metadata.zipf_exponent),
            publishers=build_publishers(
                rng.derive("publishers"), metadata.publishers, metadata.zipf_exponent
            ),
            places=build_places(rng.derive("places"), metadata.places, metadata.zipf_exponent),
        )


def _license_set(value: str) -> tuple[str, ...]:
    return tuple(sorted(value.split("+")))


def _draw_scan(pages: PagesSpec, rng: Rng) -> Scan:
    paper = rng.derive("paper").weighted(pages.paper_sizes)
    dpi = rng.derive("dpi").weighted(pages.dpi)
    width_mm, height_mm = PAPER_SIZES_MM[paper]
    producers = {index: p.weight for index, p in enumerate(pages.alto_producers)}
    return Scan(
        paper=paper,
        width=round(width_mm / _MM_PER_INCH * dpi),
        height=round(height_mm / _MM_PER_INCH * dpi),
        dpi=dpi,
        alto_version=rng.derive("alto-version").weighted(pages.alto_versions),
        producer=pages.alto_producers[rng.derive("producer").weighted(producers)],
        has_word_confidence=rng.derive("word-confidence").bernoulli(pages.p_word_confidence),
    )


def _page_types(count: int, rng: Rng, pages: PagesSpec, *, is_book: bool) -> list[str]:
    """Covers and a title page for books, a front page for issues, blanks anywhere else."""
    types = ["Blank" if rng.bernoulli(pages.p_blank) else _PAGE_TYPE_NORMAL for _ in range(count)]
    first = 0
    if is_book and count >= 4 and rng.bernoulli(pages.p_covers):
        types[0], types[-1] = "FrontCover", "BackCover"
        first = 1
    if count > first:
        types[first] = "TitlePage"
    return types


def _pages(
    key: tuple[str, ...], count: int, scan: Scan, rng: Rng, pages: PagesSpec, *, is_book: bool
) -> tuple[Node, ...]:
    nodes = []
    number = 0
    for index, page_type in enumerate(
        _page_types(count, rng.derive("types"), pages, is_book=is_book)
    ):
        is_numbered = page_type in (_PAGE_TYPE_NORMAL, "TitlePage")
        number += 1 if is_numbered else 0
        label = str(number) if is_numbered and page_type == _PAGE_TYPE_NORMAL else f"[{index + 1}]"
        nodes.append(
            Node(
                key=(*key, "page", str(index)),
                model="page",
                label=label,
                description=Description(page_number=label, page_type=page_type),
                scan=scan,
            )
        )
    return tuple(nodes)


def _title(rng: Rng, pools: Pools, low: int, high: int) -> str:
    return title(rng, pools.vocabulary, rng.integer(low, high))


# --- Monographs ---


def build_monograph(
    spec: Spec, pools: Pools, rng: Rng, key: tuple[str, ...], profile_name: str
) -> Node:
    monograph = spec.models.monograph
    assert monograph is not None  # chosen only when present in the model mix

    profile = monograph.profiles[profile_name]
    year = rng.derive("year").integer(*spec.metadata.monograph_years)
    description = Description(
        title=_title(rng.derive("title"), pools, 1, 8),
        authors=tuple(
            pools.authors.draw(rng.derive("author", i))
            for i in range(rng.derive("authors").integer(0, 3))
        ),
        publisher=pools.publishers.draw(rng.derive("publisher")),
        place=pools.places.draw(rng.derive("place")),
        date=str(year),
        language=rng.derive("language").weighted(spec.metadata.languages),
    )
    licenses = _license_set(rng.derive("licenses").weighted(monograph.licenses))
    scan = _draw_scan(spec.pages, rng.derive("scan"))

    if isinstance(profile, MonographSingle):
        count = profile.pages.sample(rng.derive("page-count"))
        pages = _pages(key, count, scan, rng.derive("pages"), spec.pages, is_book=True)
        return Node(
            key=key,
            model="monograph",
            label=description.title or "",
            description=dataclasses.replace(description, extent=f"{count} s."),
            licenses=licenses,
            children=pages,
            profile=profile_name,
        )

    return _multipart(spec, profile, rng, key, description, licenses, scan, profile_name)


def _multipart(
    spec: Spec,
    profile: MonographMultipart,
    rng: Rng,
    key: tuple[str, ...],
    description: Description,
    licenses: tuple[str, ...],
    scan: Scan,
    profile_name: str,
) -> Node:
    units = []
    for index in range(max(1, profile.units.sample(rng.derive("unit-count")))):
        unit_key = (*key, "unit", str(index))
        unit_rng = rng.derive("unit", index)
        count = profile.unit_pages.sample(unit_rng.derive("page-count"))
        units.append(
            Node(
                key=unit_key,
                model="monographunit",
                label=f"{description.title} {index + 1}",
                description=Description(
                    title=description.title,
                    part_number=str(index + 1),
                    date=description.date,
                    extent=f"{count} s.",
                ),
                licenses=licenses,
                children=_pages(
                    unit_key, count, scan, unit_rng.derive("pages"), spec.pages, is_book=True
                ),
            )
        )
    children = tuple(units)
    return Node(
        key=key,
        model="monograph",
        label=description.title or "",
        description=description,
        contains_licenses=licenses_below(children),
        children=children,
        profile=profile_name,
    )


# --- Periodicals ---


@dataclass(frozen=True)
class PeriodicalTitle:
    """Title-level draws of a periodical; its volumes are built one at a time (see corpus.py)."""

    key: tuple[str, ...]
    rng: Rng
    profile_name: str
    profile: PeriodicalProfile
    volume_count: int
    start_year: int
    title_median: float
    licenses: tuple[tuple[str, ...], ...]  # per volume
    description: Description


def open_periodical(
    spec: Spec, pools: Pools, rng: Rng, key: tuple[str, ...], profile_name: str
) -> PeriodicalTitle:
    periodical = spec.models.periodical
    assert periodical is not None  # chosen only when present in the model mix

    profile = periodical.profiles[profile_name]
    volume_count = max(1, profile.volumes.sample(rng.derive("volume-count")))
    title_text = _title(rng.derive("title"), pools, 1, 6)
    return PeriodicalTitle(
        key=key,
        rng=rng,
        profile_name=profile_name,
        profile=profile,
        volume_count=volume_count,
        start_year=rng.derive("start-year").integer(*spec.metadata.periodical_start_years),
        title_median=profile.pages_per_issue.title_median(rng.derive("title-median")),
        licenses=tuple(_volume_licenses(periodical, rng.derive("licenses"), volume_count)),
        description=Description(
            title=title_text,
            publisher=pools.publishers.draw(rng.derive("publisher")),
            place=pools.places.draw(rng.derive("place")),
            language=rng.derive("language").weighted(spec.metadata.languages),
        ),
    )


@dataclass(frozen=True)
class PeriodicalVolume:
    """Volume-level draws; its issues are built one at a time (see corpus.py)."""

    key: tuple[str, ...]
    rng: Rng
    index: int
    year: int
    scan: Scan
    licenses: tuple[str, ...]
    issue_count: int  # 0 when the volume owns its pages directly
    pages: tuple[Node, ...]  # direct pages, only when issue_count == 0

    @property
    def pid(self) -> str:
        return pid_for(self.key)


def open_volume(spec: Spec, title: PeriodicalTitle, index: int) -> PeriodicalVolume:
    rng = title.rng.derive("volume", index)
    key = (*title.key, "volume", str(index))
    scan = _draw_scan(spec.pages, rng.derive("scan"))
    profile = title.profile
    owns_pages = profile.volume_pages is not None and rng.derive("owns-pages").bernoulli(
        profile.p_volume_pages
    )
    pages: tuple[Node, ...] = ()
    if owns_pages:
        assert profile.volume_pages is not None
        count = profile.volume_pages.sample(rng.derive("page-count"))
        pages = _pages(key, count, scan, rng.derive("pages"), spec.pages, is_book=False)
    return PeriodicalVolume(
        key=key,
        rng=rng,
        index=index,
        year=title.start_year + index,
        scan=scan,
        licenses=title.licenses[index],
        issue_count=0
        if owns_pages
        else profile.issues_per_volume.sample(rng.derive("issue-count")),
        pages=pages,
    )


def build_issue(
    spec: Spec, pools: Pools, title: PeriodicalTitle, volume: PeriodicalVolume, index: int
) -> Node:
    return _issue(
        spec, pools, title.profile, volume.rng.derive("issue", index),
        (*volume.key, "issue", str(index)), volume.scan,
        date=_issue_date(volume.year, index, volume.issue_count), number=index + 1,
        title_median=title.title_median,
    )  # fmt: skip


def volume_supplements(
    spec: Spec, pools: Pools, title: PeriodicalTitle, volume: PeriodicalVolume
) -> tuple[Node, ...]:
    return _parts(
        spec, pools, volume.rng.derive("supplements"), volume.key, "supplement", volume.scan,
        count=title.profile.supplements_per_volume, pages=title.profile.supplement_pages,
    )  # fmt: skip


def close_volume(volume: PeriodicalVolume, children: tuple[Node, ...]) -> Node:
    """The volume over its pages, or the issues built so far, plus its supplements."""
    return Node(
        key=volume.key,
        model="periodicalvolume",
        label=str(volume.year),
        description=Description(part_number=str(volume.year), date=str(volume.year)),
        licenses=volume.licenses,
        children=children,
    )


def close_periodical(title: PeriodicalTitle, volumes: tuple[Node, ...]) -> Node:
    """The periodical root over the volumes built so far (all of them, or fewer at the budget)."""
    last_year = title.start_year + len(volumes) - 1
    years = f"{title.start_year}-{last_year}" if last_year > title.start_year else str(last_year)
    return Node(
        key=title.key,
        model="periodical",
        label=title.description.title or "",
        description=dataclasses.replace(title.description, date=years),
        contains_licenses=licenses_below(volumes),
        children=volumes,
        profile=title.profile_name,
    )


def _volume_licenses(periodical: PeriodicalSpec, rng: Rng, volumes: int) -> list[tuple[str, ...]]:
    """One license set per title, or two when the title switches once (older volumes first)."""
    first = rng.derive("first").weighted(periodical.licenses)
    others = {name: w for name, w in periodical.licenses.items() if name != first}
    if volumes < 2 or not others or not rng.derive("mixed").bernoulli(periodical.p_mixed_licenses):
        return [_license_set(first)] * volumes

    second = rng.derive("second").weighted(others)
    switch = rng.derive("switch").integer(1, volumes - 1)
    return [_license_set(first)] * switch + [_license_set(second)] * (volumes - switch)


def _issue_date(year: int, index: int, issues: int) -> str:
    day = datetime.date(year, 1, 1) + datetime.timedelta(days=index * 365 // max(1, issues))
    return day.isoformat()


def _issue(
    spec: Spec,
    pools: Pools,
    profile: PeriodicalProfile,
    rng: Rng,
    key: tuple[str, ...],
    scan: Scan,
    *,
    date: str,
    number: int,
    title_median: float,
) -> Node:
    count = profile.pages_per_issue.sample(rng.derive("page-count"), title_median)
    pages = _pages(key, count, scan, rng.derive("pages"), spec.pages, is_book=False)
    supplements = _parts(
        spec, pools, rng.derive("supplements"), key, "supplement", scan,
        count=profile.supplements_per_issue, pages=profile.supplement_pages,
    )  # fmt: skip
    articles = _parts(
        spec, pools, rng.derive("articles"), key, "article", scan,
        count=profile.articles_per_issue, pages=profile.article_pages,
    )  # fmt: skip
    return Node(
        key=key,
        model="periodicalitem",
        label=str(number),
        description=Description(part_number=str(number), date=date),
        children=pages + supplements + articles,
    )


def _parts(
    spec: Spec,
    pools: Pools,
    rng: Rng,
    parent_key: tuple[str, ...],
    model: str,
    scan: Scan,
    *,
    count: Count,
    pages: Count,
) -> tuple[Node, ...]:
    """Supplements or articles of a volume/issue, each owning its own pages."""
    parts = []
    for index in range(count.sample(rng.derive("count"))):
        key = (*parent_key, model, str(index))
        part_rng = rng.derive(index)
        page_count = pages.sample(part_rng.derive("page-count"))
        part_title = _title(part_rng.derive("title"), pools, 1, 6)
        parts.append(
            Node(
                key=key,
                model=model,
                label=part_title,
                description=Description(title=part_title),
                children=_pages(
                    key, page_count, scan, part_rng.derive("pages"), spec.pages, is_book=False
                ),
            )
        )
    return tuple(parts)
