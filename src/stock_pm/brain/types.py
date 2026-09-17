from __future__ import annotations

PROMPT_VERSION = "brain-phase1-v1.1"
GOLDEN_TICKERS = ("AVGO", "AAPL", "LITE")
NEWS_WINDOW_DAYS = 30
FINANCIAL_EVIDENCE_DAYS = 370
LLM_EVIDENCE_LIMIT = 80

STATE_TYPES = ("company", "industry", "macro", "event")
CLAIM_TYPES = ("structural", "operating", "valuation", "event")
CLAIM_STATUSES = (
    "emerging",
    "strongly_supported",
    "partially_supported",
    "unverified",
    "challenged",
    "contradicted",
    "background",
    "closed",
)
IMPORTANCE = ("high", "medium", "low")
CONFIDENCE = ("high", "medium", "low")
HORIZONS = ("short", "medium", "long")
LINK_DIRECTIONS = ("support", "oppose", "contextual", "irrelevant")
LINK_STRENGTHS = ("strong", "medium", "weak")
LINK_RELEVANCE = ("direct", "indirect", "background")
NEWS_LAYERS = ("material", "contextual", "noise", "uninterpreted")
QUALITY_BANDS = ("Good", "Partial", "Poor")
NUMBER_ORIGINS = ("reported", "consensus", "system_estimate", "unavailable")

HIGH_QUALITY_NEWS_HOSTS = (
    "reuters.com",
    "bloomberg.com",
    "apnews.com",
    "ft.com",
    "wsj.com",
    "sec.gov",
    "federalreserve.gov",
)
