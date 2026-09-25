# Count distributions a spec can use, each with 1–3 knobs, parsed from YAML by their `dist` field.
#
# The shapes come from calibration/findings.md: page counts are lognormal envelopes on a lattice
# of 4s and 2s (printed sheets fold), periodical sizes are two-level (a per-title median, then
# per-issue spread around it), and small counts (units per multipart monograph) are empirical.

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .sampling import Rng


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def snap_to_lattice(value: float, rng: Rng, *, p4: float, p2: float, minimum: int) -> int:
    """Round to a multiple of 4 (probability p4), of 2 (p2), or to any integer otherwise."""
    draw = rng.uniform()
    step = 4 if draw < p4 else 2 if draw < p4 + p2 else 1
    return max(minimum, step, step * round(value / step))


class Fixed(_Frozen):
    dist: Literal["fixed"]
    value: int = Field(ge=0)

    def sample(self, rng: Rng) -> int:
        return self.value


class LogNormal(_Frozen):
    dist: Literal["lognormal"]
    median: float = Field(gt=0)
    sigma: float = Field(ge=0)
    minimum: int = Field(default=1, ge=0)

    def sample(self, rng: Rng) -> int:
        return max(self.minimum, round(rng.lognormal(self.median, self.sigma)))


class LatticeLogNormal(_Frozen):
    dist: Literal["lattice_lognormal"]
    median: float = Field(gt=0)
    sigma: float = Field(ge=0)
    p4: float = Field(ge=0, le=1)
    p2: float = Field(ge=0, le=1)
    minimum: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _lattice_probabilities(self) -> "LatticeLogNormal":
        if self.p4 + self.p2 > 1:
            raise ValueError(f"p4 + p2 must be <= 1, got {self.p4} + {self.p2}")
        return self

    def sample(self, rng: Rng) -> int:
        value = rng.lognormal(self.median, self.sigma)
        return snap_to_lattice(value, rng, p4=self.p4, p2=self.p2, minimum=self.minimum)


class Poisson(_Frozen):
    dist: Literal["poisson"]
    mean: float = Field(ge=0)

    def sample(self, rng: Rng) -> int:
        return rng.poisson(self.mean)


class Table(_Frozen):
    """An empirical distribution over small counts, e.g. units per multipart monograph."""

    dist: Literal["table"]
    weights: dict[int, float]

    @field_validator("weights")
    @classmethod
    def _positive(cls, weights: dict[int, float]) -> dict[int, float]:
        if not weights or any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError(f"table weights must be non-negative with a positive sum: {weights}")
        return weights

    def sample(self, rng: Rng) -> int:
        return rng.weighted(self.weights)


Count = Annotated[
    Fixed | LogNormal | LatticeLogNormal | Poisson | Table, Field(discriminator="dist")
]


class TitleVarying(_Frozen):
    """Two-level lattice lognormal: each title draws its own median, each unit varies around it."""

    median: float = Field(gt=0)
    sigma_between: float = Field(ge=0)
    sigma_within: float = Field(ge=0)
    p4: float = Field(ge=0, le=1)
    p2: float = Field(ge=0, le=1)
    minimum: int = Field(default=1, ge=1)

    def title_median(self, rng: Rng) -> float:
        return rng.lognormal(self.median, self.sigma_between)

    def sample(self, rng: Rng, title_median: float) -> int:
        value = rng.lognormal(title_median, self.sigma_within)
        return snap_to_lattice(value, rng, p4=self.p4, p2=self.p2, minimum=self.minimum)


class IssueCount(_Frozen):
    """Issues per volume: the nominal frequency, a small spread, and some incomplete volumes."""

    nominal: int = Field(ge=1)
    sigma: float = Field(ge=0)
    p_incomplete: float = Field(ge=0, le=1)

    def sample(self, rng: Rng) -> int:
        count = max(1, round(self.nominal * math.exp(self.sigma * rng.normal())))
        if rng.bernoulli(self.p_incomplete):
            count = math.ceil(count * rng.between(0.1, 1.0))
        return max(1, count)
