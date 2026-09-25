# Synthetic text: a Czech-like vocabulary sampled by Zipf's law, and pools of names.
#
# Plain lorem ipsum has ~70 distinct words, which would give Solr a tiny fulltext index with
# degenerate posting lists. A large vocabulary with Zipf frequencies gives realistic term
# statistics, and frequent words are short, as in natural language.

import bisect
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .sampling import Rng

_ONSETS = (
    "", "b", "c", "č", "d", "h", "ch", "j", "k", "l", "m", "n", "p", "r", "ř", "s", "š", "t",
    "v", "z", "ž", "br", "dr", "hl", "kr", "pr", "st", "tr", "vl", "zn",
)  # fmt: skip
_NUCLEI = ("a", "e", "i", "o", "u", "y", "á", "é", "í", "ou", "ů")
_CODAS = ("", "", "", "", "k", "l", "m", "n", "s", "t", "ch", "st")


def _syllable(rng: Rng) -> str:
    return rng.choice(_ONSETS) + rng.choice(_NUCLEI) + rng.choice(_CODAS)


def _word(rng: Rng, syllables: int) -> str:
    return "".join(_syllable(rng) for _ in range(syllables))


@dataclass(frozen=True)
class ZipfPool:
    """Distinct strings ranked by frequency; rank r is drawn with weight 1 / r^exponent."""

    items: tuple[str, ...]
    cumulative: tuple[float, ...]

    @classmethod
    def build(cls, items: Sequence[str], exponent: float) -> "ZipfPool":
        weights = (1.0 / (rank**exponent) for rank in range(1, len(items) + 1))
        return cls(tuple(items), tuple(itertools.accumulate(weights)))

    def draw(self, rng: Rng) -> str:
        threshold = rng.uniform() * self.cumulative[-1]
        return self.items[bisect.bisect_right(self.cumulative, threshold)]


def _distinct(rng: Rng, count: int, make: Callable[[Rng, int], str]) -> list[str]:
    """Draw `count` distinct strings; make(rng, rank) builds a candidate for the next rank.

    Pools are built once per corpus, so one sequential stream is enough (and much faster than a
    keyed stream per attempt).
    """
    seen: set[str] = set()
    items: list[str] = []
    for _ in itertools.count():
        if len(items) == count:
            break
        candidate = make(rng, len(items))
        if candidate not in seen:
            seen.add(candidate)
            items.append(candidate)
    return items


def _vocabulary_word(rng: Rng, rank: int) -> str:
    # Frequent (low-rank) words get fewer syllables.
    syllables = 1 + min(3, rank.bit_length() // 4) + (1 if rng.bernoulli(0.3) else 0)
    return _word(rng, syllables)


def _person_name(rng: Rng, rank: int) -> str:
    # As catalogs write them: "Surname, Given".
    return f"{_word(rng, rng.integer(2, 3)).capitalize()}, {_word(rng, 2).capitalize()}"


_PUBLISHER_KINDS = ("Nakladatelství", "Tiskárna", "Vydavatelství", "Knihtiskárna", "Spolek")


def _publisher(rng: Rng, rank: int) -> str:
    return f"{rng.choice(_PUBLISHER_KINDS)} {_word(rng, rng.integer(2, 3)).capitalize()}"


def _place(rng: Rng, rank: int) -> str:
    return _word(rng, rng.integer(2, 3)).capitalize()


def build_vocabulary(rng: Rng, size: int, exponent: float) -> ZipfPool:
    return ZipfPool.build(_distinct(rng, size, _vocabulary_word), exponent)


def build_names(rng: Rng, size: int, exponent: float) -> ZipfPool:
    return ZipfPool.build(_distinct(rng, size, _person_name), exponent)


def build_publishers(rng: Rng, size: int, exponent: float) -> ZipfPool:
    return ZipfPool.build(_distinct(rng, size, _publisher), exponent)


def build_places(rng: Rng, size: int, exponent: float) -> ZipfPool:
    return ZipfPool.build(_distinct(rng, size, _place), exponent)


def title(rng: Rng, vocabulary: ZipfPool, words: int) -> str:
    text = " ".join(vocabulary.draw(rng) for _ in range(max(1, words)))
    return text[:1].upper() + text[1:]
