"""demand/ — keyword-demand lookup over official APIs (no browser).

The harvest side reads demand the way the capture side reads answers: from the
real surface. This package is the *deterministic* half of that — it asks the
search platforms' own APIs for volume, and never guesses a number. When no
provider is configured for a locale it says so (`status="unavailable"`) instead
of returning a plausible figure.

Authority: `pipeline/INTERFACES.md §8`. Process: `harvest/METHODOLOGY.md §3`.
"""

from demand.schema import DemandStat, RelatedPhrase, SuggestHit

__all__ = ["DemandStat", "RelatedPhrase", "SuggestHit"]
