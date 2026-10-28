# Corpus spec: the YAML that fully describes what a generated corpus looks like.
#
# A spec is model mix -> profiles per model -> distributions per profile.
# Mixes are page shares: what fraction of generated pages each model/profile gets (mix.py).
# Size and seed are not part of it, so one spec drives corpora of any size. The spec is parsed once
# here and trusted everywhere else.

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .distributions import Count, IssueCount, TitleVarying

# Paper sizes in millimetres (width, height), portrait.
PAPER_SIZES_MM: dict[str, tuple[int, int]] = {
    "A6": (105, 148),
    "A5": (148, 210),
    "B5": (176, 250),
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
}
ALTO_VERSIONS = ("v2", "v3", "v4")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_weights(weights: dict[str, float], what: str) -> dict[str, float]:
    if not weights or any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError(f"{what} must be non-negative with a positive sum, got {weights}")
    return weights


Weights = dict[str, float]


# --- Monographs ---


class MonographSingle(_Frozen):
    kind: Literal["single"]
    page_share: float = Field(gt=0)
    pages: Count


class MonographMultipart(_Frozen):
    kind: Literal["multipart"]
    page_share: float = Field(gt=0)
    units: Count
    unit_pages: Count


MonographProfile = Annotated[MonographSingle | MonographMultipart, Field(discriminator="kind")]


class MonographSpec(_Frozen):
    page_share: float = Field(gt=0)  # share of corpus pages; see mix.py
    profiles: dict[str, MonographProfile]
    licenses: Weights  # license sets ("dnnto+onsite") set on the root or on each unit

    @field_validator("licenses")
    @classmethod
    def _licenses(cls, weights: Weights) -> Weights:
        return _check_weights(weights, "monograph licenses")


# --- Periodicals ---


class PeriodicalProfile(_Frozen):
    page_share: float = Field(gt=0)  # share of periodical pages
    volumes: Count
    issues_per_volume: IssueCount
    pages_per_issue: TitleVarying
    p_volume_pages: float = Field(default=0, ge=0, le=1)  # volume owns pages instead of issues
    volume_pages: Count | None = None
    supplements_per_volume: Count
    supplements_per_issue: Count
    supplement_pages: Count
    articles_per_issue: Count
    article_pages: Count

    @model_validator(mode="after")
    def _volume_pages(self) -> "PeriodicalProfile":
        if self.p_volume_pages > 0 and self.volume_pages is None:
            raise ValueError("volume_pages is required when p_volume_pages > 0")
        return self


class PeriodicalSpec(_Frozen):
    page_share: float = Field(gt=0)
    profiles: dict[str, PeriodicalProfile]
    licenses: Weights  # license sets, set on each volume
    p_mixed_licenses: float = Field(ge=0, le=1)  # title switches license set once, by volume order

    @field_validator("licenses")
    @classmethod
    def _licenses(cls, weights: Weights) -> Weights:
        return _check_weights(weights, "periodical licenses")


class ModelsSpec(_Frozen):
    monograph: MonographSpec | None = None
    periodical: PeriodicalSpec | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ModelsSpec":
        if self.monograph is None and self.periodical is None:
            raise ValueError("a spec needs at least one root model")
        return self

    def page_shares(self) -> dict[str, float]:
        shares: dict[str, float] = {}
        if self.monograph is not None:
            shares["monograph"] = self.monograph.page_share
        if self.periodical is not None:
            shares["periodical"] = self.periodical.page_share
        return shares


# --- Pages and ALTO ---


class AltoProducer(_Frozen):
    creator: str
    name: str
    version: str
    weight: float = Field(gt=0)


class PagesSpec(_Frozen):
    paper_sizes: Weights
    dpi: dict[int, float]
    p_blank: float = Field(ge=0, le=1)
    p_covers: float = Field(ge=0, le=1)  # monograph has front/back cover pages
    lines: Count
    words_per_line: Count
    lines_per_block: Count
    alto_versions: Weights
    alto_producers: list[AltoProducer] = Field(min_length=1)
    p_word_confidence: float = Field(ge=0, le=1)  # ALTO carries WC per string (per document)

    @field_validator("paper_sizes")
    @classmethod
    def _known_sizes(cls, weights: Weights) -> Weights:
        unknown = set(weights) - set(PAPER_SIZES_MM)
        if unknown:
            raise ValueError(
                f"unknown paper sizes {sorted(unknown)}, known: {list(PAPER_SIZES_MM)}"
            )
        return _check_weights(weights, "paper sizes")

    @field_validator("alto_versions")
    @classmethod
    def _known_versions(cls, weights: Weights) -> Weights:
        unknown = set(weights) - set(ALTO_VERSIONS)
        if unknown:
            raise ValueError(f"unknown ALTO versions {sorted(unknown)}, known: {ALTO_VERSIONS}")
        return _check_weights(weights, "ALTO versions")


# --- Text and metadata ---


class TextSpec(_Frozen):
    vocabulary_size: int = Field(ge=100)
    zipf_exponent: float = Field(gt=0)


class MetadataSpec(_Frozen):
    authors: int = Field(ge=1)  # pool sizes; names repeat by Zipf, as in real catalogs
    publishers: int = Field(ge=1)
    places: int = Field(ge=1)
    zipf_exponent: float = Field(gt=0)
    languages: Weights
    monograph_years: tuple[int, int]
    periodical_start_years: tuple[int, int]

    @field_validator("monograph_years", "periodical_start_years")
    @classmethod
    def _ordered(cls, years: tuple[int, int]) -> tuple[int, int]:
        if years[0] > years[1]:
            raise ValueError(f"year range must be ordered, got {years}")
        return years


class ImagesSpec(_Frozen):
    base_url: str  # IIP-style image server; pages reference {base_url}/{uuid}/big.jpg etc.


class Spec(_Frozen):
    name: str
    models: ModelsSpec
    pages: PagesSpec
    text: TextSpec
    metadata: MetadataSpec
    images: ImagesSpec

    def digest(self) -> str:
        """Stable hash of the parsed spec: part of the corpus cache key."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_spec(path: Path) -> Spec:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return Spec.model_validate(raw)
