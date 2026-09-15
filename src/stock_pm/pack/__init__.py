"""Decision-system presentation pack: overview + stock + review.

Consumes existing watchlist, trusted events, news, quotes, environment,
tape, and predictions. Does not invent a second product or fake certainty.
"""

from .assemble import build_overview, build_review, build_stock
from .copy import HOLDINGS_BANNED, strip_holdings

__all__ = [
    "HOLDINGS_BANNED",
    "build_overview",
    "build_review",
    "build_stock",
    "strip_holdings",
]
