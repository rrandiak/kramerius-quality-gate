# Page-share quota: deterministic choice of what to generate next.
#
# Drawing root models (and profiles) at random by title share leaves small corpora with the wrong
# mix: periodicals are 1.8% of MZK roots but 21% of pages, so a 10k-page corpus would usually hold
# none. Instead every next root goes to whatever is furthest below its target share of pages, so
# every prefix of the corpus (10k, 100k, ...) has the production page mix. The choice depends only
# on earlier roots, which keeps corpora prefix-stable.

from collections.abc import Mapping


class PageQuota:
    def __init__(self, shares: Mapping[str, float]) -> None:
        total = sum(shares.values())
        if not shares or total <= 0 or any(share < 0 for share in shares.values()):
            raise ValueError(
                f"page shares must be non-negative with a positive sum: {dict(shares)}"
            )

        # Ties (e.g. the very first pick) go to the largest share, then by name.
        self._targets = {
            key: share / total
            for key, share in sorted(shares.items(), key=lambda item: (-item[1], item[0]))
        }
        self._pages = dict.fromkeys(self._targets, 0)

    def next(self) -> str:
        """The key most below its target share of the pages generated so far."""
        total = sum(self._pages.values())
        return max(self._targets, key=lambda key: self._targets[key] * total - self._pages[key])

    def record(self, key: str, pages: int) -> None:
        self._pages[key] += pages
