# Count distributions: lattice snapping, knob validation, and the two-level issue model.

import pytest
from pydantic import TypeAdapter, ValidationError

from qg.generator.distributions import Count, IssueCount, LatticeLogNormal, TitleVarying
from qg.generator.sampling import Rng

COUNT = TypeAdapter(Count)


def _lattice(p4: float, p2: float) -> LatticeLogNormal:
    return LatticeLogNormal(dist="lattice_lognormal", median=30, sigma=0.8, p4=p4, p2=p2)


def test_full_p4_gives_multiples_of_four() -> None:
    rng = Rng("lattice")

    samples = [_lattice(1.0, 0.0).sample(rng.derive(i)) for i in range(500)]

    assert all(value % 4 == 0 for value in samples)


def test_full_p2_gives_even_counts() -> None:
    rng = Rng("lattice")

    samples = [_lattice(0.0, 1.0).sample(rng.derive(i)) for i in range(500)]

    assert all(value % 2 == 0 for value in samples)


def test_lattice_probabilities_must_not_exceed_one() -> None:
    with pytest.raises(ValidationError, match="p4 \\+ p2"):
        _lattice(0.7, 0.5)


def test_count_is_parsed_by_its_dist_field() -> None:
    count = COUNT.validate_python({"dist": "table", "weights": {2: 1.0}})

    assert count.sample(Rng("table")) == 2


def test_issues_without_spread_equal_the_nominal_frequency() -> None:
    issues = IssueCount(nominal=12, sigma=0.0, p_incomplete=0.0)

    assert {issues.sample(Rng("issues", i)) for i in range(100)} == {12}


def test_issue_pages_centre_on_the_title_median() -> None:
    pages = TitleVarying(median=20, sigma_between=0.0, sigma_within=0.3, p4=0.0, p2=0.0)
    rng = Rng("title")
    title_median = pages.title_median(rng)

    samples = sorted(pages.sample(rng.derive(i), title_median) for i in range(2001))

    assert abs(samples[1000] - 20) <= 1
