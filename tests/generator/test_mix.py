# Page-share quota: every prefix of the generated sequence tracks the target page mix.

import pytest

from qg.generator.mix import PageQuota


def test_first_pick_is_the_largest_share() -> None:
    quota = PageQuota({"periodical": 0.21, "monograph": 0.79})

    assert quota.next() == "monograph"


def test_page_mix_tracks_targets_despite_uneven_sizes() -> None:
    quota = PageQuota({"small": 0.5, "large": 0.5})
    sizes = {"small": 10, "large": 1000}
    pages = {"small": 0, "large": 0}

    for _ in range(300):
        key = quota.next()
        quota.record(key, sizes[key])
        pages[key] += sizes[key]

    assert pages["small"] / sum(pages.values()) == pytest.approx(0.5, abs=0.02)


def test_negative_share_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        PageQuota({"a": 1.0, "b": -0.5})
