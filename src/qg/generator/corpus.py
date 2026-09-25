# Corpus generation: a stream of units (a monograph, or the next issue of a periodical title)
# until the page budget is met, written as FOXML + a manifest.
#
# The page-share quota (mix.py) picks the model and profile of each unit from the units before it.
# Periodicals are scheduled issue by issue, one open title (and volume) per profile: a daily title
# is ~30k pages and one of its volumes ~2-4k, either of which would swallow a small corpus. Root i
# draws from the stream (spec digest, seed, "root", i), so a corpus of N pages is a prefix of a
# corpus of M > N pages from the same spec and seed. Only volumes and titles still open at the
# budget differ: their FOXML lists the children emitted so far; corpus.json names them `truncated`.

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

from .alto import compose
from .foxml import datastreams, foxml_bytes
from .mix import PageQuota
from .sampling import Rng
from .spec import Spec
from .structure import (
    PeriodicalTitle,
    PeriodicalVolume,
    Pools,
    build_issue,
    build_monograph,
    close_periodical,
    close_volume,
    open_periodical,
    open_volume,
    volume_supplements,
)
from .tree import Node, pid_for

FOXML_DIR = "foxml"
MANIFEST_FILE = "manifest.jsonl"
SUMMARY_FILE = "corpus.json"


class CorpusExistsError(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(f"output directory {path} is not empty; generated corpora never overwrite")


@dataclass(frozen=True)
class CorpusOptions:
    seed: int
    pages: int  # page budget; the corpus stops at the first unit (monograph/volume) reaching it
    created: str  # timestamp written into every object, fixed for reproducibility


@dataclass(frozen=True)
class CorpusSummary:
    spec: str
    spec_digest: str
    generator_version: str
    seed: int
    pages_requested: int
    pages: int
    roots: int
    truncated: list[str]  # volumes and titles closed at the budget, with fewer children
    objects: dict[str, int]
    created: str


@dataclass(frozen=True)
class Emission:
    """A generated piece to write: a whole subtree, or only its top object when shallow."""

    node: Node
    parent: str | None
    root: str
    is_shallow: bool = False  # a volume or periodical root whose children were emitted earlier
    is_truncated: bool = False  # closed at the page budget, before its last child


def corpus_rng(spec: Spec, options: CorpusOptions) -> Rng:
    """The root stream: keyed by spec digest too, so different specs never share pids."""
    return Rng("qg", spec.digest(), f"seed-{options.seed}")


@dataclass
class _OpenTitle:
    title: PeriodicalTitle
    volumes: list[Node] = field(default_factory=list)
    volume: PeriodicalVolume | None = None
    issues: list[Node] = field(default_factory=list)


def generate(spec: Spec, options: CorpusOptions, pools: Pools) -> Iterator[Emission]:
    root_rng = corpus_rng(spec, options)
    models = PageQuota(spec.models.page_shares())
    profiles = {
        model: PageQuota({name: p.page_share for name, p in model_spec.profiles.items()})
        for model, model_spec in (
            ("monograph", spec.models.monograph),
            ("periodical", spec.models.periodical),
        )
        if model_spec is not None
    }
    open_titles: dict[str, _OpenTitle] = {}
    pages = roots = 0
    while pages < options.pages:
        model = models.next()
        profile = profiles[model].next()

        if model == "monograph":
            key = (*root_rng.key, "root", str(roots))
            unit = build_monograph(spec, pools, root_rng.derive("root", roots), key, profile)
            roots += 1
            emitted = [Emission(unit, None, unit.pid)]
        else:
            if profile not in open_titles:
                key = (*root_rng.key, "root", str(roots))
                title = open_periodical(spec, pools, root_rng.derive("root", roots), key, profile)
                open_titles[profile] = _OpenTitle(title)
                roots += 1
            emitted = _next_periodical_unit(spec, pools, open_titles, profile)

        size = sum(e.node.page_count for e in emitted if not e.is_shallow)
        models.record(model, size)
        profiles[model].record(profile, size)
        pages += size
        yield from emitted

    for state in open_titles.values():
        yield from _close_title(spec, pools, state, is_truncated=True)


def _next_periodical_unit(
    spec: Spec, pools: Pools, open_titles: dict[str, _OpenTitle], profile: str
) -> list[Emission]:
    """The next issue of the profile's open title, closing its volume/title when complete."""
    state = open_titles[profile]
    title = state.title
    root = pid_for(title.key)
    if state.volume is None:
        state.volume = open_volume(spec, title, len(state.volumes))

    volume = state.volume
    emitted: list[Emission] = []
    if volume.issue_count:
        issue = build_issue(spec, pools, title, volume, len(state.issues))
        state.issues.append(issue)
        emitted.append(Emission(issue, volume.pid, root))
    if len(state.issues) == volume.issue_count:
        emitted += _close_volume(spec, pools, state, is_truncated=False)
    if len(state.volumes) == title.volume_count:
        del open_titles[profile]
        emitted += _close_title(spec, pools, state, is_truncated=False)
    return emitted


def _close_volume(
    spec: Spec, pools: Pools, state: _OpenTitle, *, is_truncated: bool
) -> list[Emission]:
    volume = state.volume
    assert volume is not None  # only called with an open volume
    root = pid_for(state.title.key)
    supplements = volume_supplements(spec, pools, state.title, volume)
    # Pages owned directly by the volume are written with it; issues were written one by one.
    closed = close_volume(volume, volume.pages + tuple(state.issues) + supplements)
    state.volumes.append(closed)
    state.volume, state.issues = None, []
    emitted = [Emission(part, volume.pid, root) for part in volume.pages + supplements]
    emitted.append(Emission(closed, root, root, is_shallow=True, is_truncated=is_truncated))
    return emitted


def _close_title(
    spec: Spec, pools: Pools, state: _OpenTitle, *, is_truncated: bool
) -> list[Emission]:
    emitted = _close_volume(spec, pools, state, is_truncated=True) if state.volume else []
    root = close_periodical(state.title, tuple(state.volumes))
    emitted.append(Emission(root, None, root.pid, is_shallow=True, is_truncated=is_truncated))
    return emitted


def _object_bytes(node: Node, spec: Spec, pools: Pools, created: str) -> bytes:
    layout = None
    if node.model == "page":
        assert node.scan is not None  # every page carries its document's scan
        layout = compose(
            Rng(*node.key, "text"), spec.pages, node.scan, pools.vocabulary,
            is_blank=node.description.page_type == "Blank",
        )  # fmt: skip
    return foxml_bytes(node, datastreams(node, layout, spec.images.base_url, created), created)


def _manifest_rows(emission: Emission) -> Iterator[dict[str, object]]:
    def rows(node: Node, parent: str | None) -> Iterator[dict[str, object]]:
        yield {
            "pid": node.pid,
            "model": node.model,
            "profile": node.profile,
            "parent": parent,
            "root": emission.root,
            "children": len(node.children),
            "pages": node.page_count,
            "licenses": list(node.licenses),
        }
        if emission.is_shallow:
            return
        for child in node.children:
            yield from rows(child, node.pid)

    return rows(emission.node, emission.parent)


def write_corpus(spec: Spec, options: CorpusOptions, out: Path) -> CorpusSummary:
    if out.exists() and any(out.iterdir()):
        raise CorpusExistsError(out)

    pools = Pools.build(spec, corpus_rng(spec, options).derive("pools"))
    objects: Counter[str] = Counter()
    pages = roots = 0
    truncated: list[str] = []
    (out / FOXML_DIR).mkdir(parents=True, exist_ok=True)
    with (out / MANIFEST_FILE).open("w") as manifest:
        for emission in generate(spec, options, pools):
            root_dir = out / FOXML_DIR / emission.root.removeprefix("uuid:")
            root_dir.mkdir(exist_ok=True)
            nodes = [emission.node] if emission.is_shallow else list(emission.node.walk())
            for node in nodes:
                (root_dir / f"{node.pid.removeprefix('uuid:')}.xml").write_bytes(
                    _object_bytes(node, spec, pools, options.created)
                )
                objects[node.model] += 1
            for row in _manifest_rows(emission):
                manifest.write(json.dumps(row, separators=(",", ":")) + "\n")
            if emission.parent is None:
                roots += 1
            if not emission.is_shallow:
                pages += emission.node.page_count
            if emission.is_truncated:
                truncated.append(emission.node.pid)

    summary = CorpusSummary(
        spec=spec.name,
        spec_digest=spec.digest(),
        generator_version=version("kramerius-quality-gate"),
        seed=options.seed,
        pages_requested=options.pages,
        pages=pages,
        roots=roots,
        truncated=truncated,
        objects=dict(sorted(objects.items())),
        created=options.created,
    )
    (out / SUMMARY_FILE).write_text(json.dumps(summary.__dict__, indent=1) + "\n")
    return summary
