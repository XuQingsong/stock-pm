from __future__ import annotations

PROMPT_VERSION = "brain-v1"
GOLDEN_TICKERS = ("AVGO", "AAPL", "LITE")
NEWS_WINDOW_DAYS = 30
FINANCIAL_EVIDENCE_DAYS = 370
LLM_EVIDENCE_LIMIT = 80
TAVILY_SEARCH_BUDGET = 10
EXA_SEARCH_BUDGET = 10
DRIVER_UNIVERSE_MIN = 8
DRIVER_UNIVERSE_MAX = 15
CORE_CLAIM_MIN = 3
CORE_CLAIM_MAX = 5
TRANSMISSION_MAX_STEPS = 6

STATE_TYPES = (
    "company",
    "industry",
    "macro",
    "event",
    "event_shock",
    "market_expectation",
    "data_quality",
)
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
LIFECYCLES = (
    "emerging",
    "core",
    "challenged",
    "background",
    "confirmed",
    "contradicted",
    "closed",
)
LIFECYCLE_ACTIONS = ("promote", "demote", "merge", "split", "close", "update")
DRIVER_CATEGORIES = (
    "demand",
    "market_share",
    "pricing",
    "volume",
    "product_mix",
    "margin",
    "customer_concentration",
    "supplier_dependency",
    "capacity",
    "competition",
    "technology",
    "regulation",
    "macro",
    "capital_allocation",
    "accounting_quality",
    "valuation",
)
DRIVER_STATUSES = ("active", "watch", "retired", "closed")
FACT_RELIABILITY = ("direct_fact", "derived_fact", "opinion", "estimate", "signal", "rumor")
KNOWLEDGE_LAYERS = ("material", "context", "noise")
EVENT_TYPES = (
    "earnings",
    "guidance",
    "capex",
    "product",
    "regulation",
    "competition",
    "macro",
    "mna",
    "litigation",
    "customer",
    "supply",
    "other",
)
EXPOSURE_TYPES = ("customer", "supplier", "product", "geographic", "competitive", "financial", "technology")
FINANCIAL_METRICS = (
    "revenue",
    "volume",
    "ASP",
    "gross_margin",
    "operating_margin",
    "opex",
    "capex",
    "FCF",
    "EPS",
    "multiple",
    "WACC",
    "terminal_growth",
)
RUN_MODES = ("full", "incremental")
CRITIC_ISSUE_TYPES = (
    "missed_material_driver",
    "unsupported_leap",
    "weak_causal_link",
    "missing_counter_evidence",
    "alternative_hypothesis",
    "event_overreaction",
    "wrong_base_case_update",
    "evidence_boundary_violation",
)
CRITIC_SEVERITY = ("low", "medium", "high")
IMPACT_SCOPES = ("scenario_only", "base")
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
