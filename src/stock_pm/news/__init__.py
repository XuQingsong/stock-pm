"""News information layer, N0: RawArticle contract, time normalization,
adapters over existing fetchers, article dedupe, and source health."""

from .contract import RawArticle
from .dedupe import dedupe_articles
from .health import DEFAULT_POLICIES, evaluate_health
from .timeutil import market_session, normalize_published, reaction_date

__all__ = [
    "DEFAULT_POLICIES",
    "RawArticle",
    "dedupe_articles",
    "evaluate_health",
    "market_session",
    "normalize_published",
    "reaction_date",
]
