# Deterministic sampling: same key, same stream; derived streams are independent of draw order.

from qg.generator.sampling import Rng


def test_same_key_gives_same_stream() -> None:
    first = [Rng("a", 1).uniform() for _ in range(3)]
    second = [Rng("a", 1).uniform() for _ in range(3)]

    assert first == second


def test_derived_stream_equals_stream_with_extended_key() -> None:
    parent = Rng("corpus", "seed-1")
    parent.uniform()  # drawing from the parent must not shift the child

    assert parent.derive("root", 3).uniform() == Rng("corpus", "seed-1", "root", 3).uniform()


def test_poisson_mean_is_close_to_requested() -> None:
    rng = Rng("poisson")

    small = [rng.poisson(3.0) for _ in range(20000)]
    large = [rng.poisson(80.0) for _ in range(20000)]

    assert abs(sum(small) / len(small) - 3.0) < 0.1
    assert abs(sum(large) / len(large) - 80.0) < 1.0


def test_weighted_never_picks_zero_weight() -> None:
    rng = Rng("weighted")

    picks = {rng.weighted({"never": 0.0, "always": 1.0}) for _ in range(1000)}

    assert picks == {"always"}


def test_integer_covers_both_bounds() -> None:
    rng = Rng("integer")

    values = {rng.integer(2, 4) for _ in range(1000)}

    assert values == {2, 3, 4}
