# Deterministic random sampling for the corpus generator.
#
# Every draw goes through random.Random.random() only. CPython guarantees that stream for a given
# seed, while the higher-level helpers (gauss, choices, numpy distributions) may change between
# versions. Keeping to the raw stream keeps a (spec, seed, size) corpus byte-identical across
# Python and library upgrades.

import math
import random
from collections.abc import Mapping, Sequence
from statistics import NormalDist

_STANDARD_NORMAL = NormalDist()
_SMALLEST_UNIFORM = 1e-12
# Above this mean, Poisson inversion gets slow and a normal approximation is accurate enough.
_POISSON_NORMAL_THRESHOLD = 50.0


class Rng:
    """A random stream identified by a key path, e.g. ("seed-1", "root", 42, "volume", 3).

    Streams are derived by extending the key, never by drawing from a parent, so adding or
    removing draws in one part of the tree never shifts the numbers of another part. That is
    what makes a corpus prefix-stable.
    """

    def __init__(self, *key: str | int) -> None:
        self.key = tuple(str(part) for part in key)
        self._random = random.Random("/".join(self.key))

    def derive(self, *key: str | int) -> "Rng":
        return Rng(*self.key, *key)

    def uniform(self) -> float:
        """Uniform in (0, 1): zero is excluded so it is safe for inverse CDFs and logs."""
        return max(self._random.random(), _SMALLEST_UNIFORM)

    def between(self, low: float, high: float) -> float:
        return low + (high - low) * self.uniform()

    def integer(self, low: int, high: int) -> int:
        """Uniform integer in [low, high], both inclusive."""
        if high < low:
            raise ValueError(f"empty integer range [{low}, {high}]")

        return min(low + int(self.uniform() * (high - low + 1)), high)

    def normal(self) -> float:
        return _STANDARD_NORMAL.inv_cdf(self.uniform())

    def lognormal(self, median: float, sigma: float) -> float:
        return median * math.exp(sigma * self.normal())

    def bernoulli(self, probability: float) -> bool:
        return self.uniform() < probability

    def poisson(self, mean: float) -> int:
        if mean <= 0:
            return 0

        if mean > _POISSON_NORMAL_THRESHOLD:
            return max(0, round(mean + math.sqrt(mean) * self.normal()))

        # Inversion: walk the CDF until it passes one uniform draw.
        threshold = self.uniform()
        probability = math.exp(-mean)
        cumulative = probability
        count = 0
        while cumulative < threshold:
            count += 1
            probability *= mean / count
            cumulative += probability
        return count

    def choice[T](self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("cannot choose from an empty sequence")

        return items[self.integer(0, len(items) - 1)]

    def weighted[K](self, weights: Mapping[K, float]) -> K:
        """Pick a key with probability proportional to its weight (in the mapping's order)."""
        total = sum(weights.values())
        if total <= 0:
            raise ValueError(f"weights must sum to a positive number, got {dict(weights)}")

        threshold = self.uniform() * total
        cumulative = 0.0
        last = None
        for key, weight in weights.items():
            cumulative += weight
            last = key
            if threshold < cumulative:
                return key
        assert last is not None  # total > 0 guarantees at least one key
        return last
