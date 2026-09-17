from __future__ import annotations

PROMPT_VERSION = "brain-integrity-v1"
GOLDEN_TICKERS = ("AVGO", "AAPL", "LITE")
NEWS_WINDOW_DAYS = 30
FINANCIAL_EVIDENCE_DAYS = 370
LLM_EVIDENCE_LIMIT = 80
TAVILY_SEARCH_BUDGET = 10
EXA_SEARCH_BUDGET = 10

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
SOURCE_RELATIONSHIPS = (
    "issuer_primary",
    "related_entity_primary",
    "independent_media",
    "industry_peer",
    "aggregator",
    "community",
    "unknown",
)
EXTERNAL_VALIDATION_RELATIONSHIPS = (
    "related_entity_primary",
    "independent_media",
    "industry_peer",
)
WEAK_RELATIONSHIPS = ("aggregator", "community", "unknown")
STRONG_LINK_QUALITY = ("strong", "medium")
LIFECYCLES = ("core", "challenged", "background", "closed")
MATCH_ACTIONS = ("update_existing", "create_new", "merge_into_existing", "split_from_existing")
CLAIM_SUBJECTS = (
    "ai_custom_silicon",
    "services_mix",
    "hardware_demand",
    "optical_demand",
    "margin_quality",
    "demand_duration",
    "valuation",
    "customer_concentration",
)
CLAIM_DIMENSIONS = (
    "growth_duration",
    "structural_vs_cyclical",
    "customer_concentration",
    "margin_quality",
    "valuation_sensitivity",
    "decision_variable",
)

HIGH_QUALITY_NEWS_HOSTS = (
    "reuters.com",
    "bloomberg.com",
    "apnews.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "sec.gov",
    "federalreserve.gov",
)
