from __future__ import annotations

PROMPT_VERSION = "brain-v1"
BRAIN_PHASE = "phase0"
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

COGNITIVE_LAYERS = (
    "observation",
    "market",
    "state",
    "investment_reasoning",
    "structural_knowledge",
)
OBJECT_LAYER = {
    "observation": "observation",
    "news": "observation",
    "fact": "observation",
    "event": "observation",
    "signal": "observation",
    "price": "observation",
    "market_state": "market",
    "market_driver": "market",
    "expectation": "market",
    "market_attention": "market",
    "price_reaction": "market",
    "state": "state",
    "company_state": "state",
    "industry_state": "state",
    "macro_state": "state",
    "exposure": "state",
    "shadow_state": "state",
    "driver": "investment_reasoning",
    "value_driver": "investment_reasoning",
    "claim": "investment_reasoning",
    "core_claim": "investment_reasoning",
    "financial_impact": "investment_reasoning",
    "scenario": "investment_reasoning",
    "business_model": "structural_knowledge",
    "industry_structure": "structural_knowledge",
    "causal_edge": "structural_knowledge",
    "causal_relationship": "structural_knowledge",
    "causal_gap": "structural_knowledge",
    "financial_metric": "investment_reasoning",
}
LAYER_RANK = {
    "observation": 1,
    "market": 2,
    "state": 3,
    "investment_reasoning": 4,
    "structural_knowledge": 5,
}
LAYER_SPEED = {
    "observation": "fastest",
    "market": "fast",
    "state": "medium",
    "investment_reasoning": "slow",
    "structural_knowledge": "slowest",
}
FAST_LAYERS = ("observation", "market")
BRAIN_RUNTIME = "phase3"
MARKET_ALIGNMENTS = ("aligned", "partial", "unexplained", "unknown")
NOW_CHAIN_QUESTIONS = (
    "what_happened",
    "why_it_affects_company",
    "path_to_driver_claim",
    "what_market_is_trading",
)
DEFAULT_RUN_MODE = "incremental"
PROPOSAL_DECISIONS = ("approve", "reject", "requires_review")
SHADOW_STATUSES = ("open", "watching", "confirmed", "closed")
CAUSAL_EDGE_STATUSES = (
    "candidate",
    "observed",
    "supported",
    "established",
    "challenged",
    "deprecated",
)
CAUSAL_RELATIONSHIP_TYPES = (
    "event_to_state",
    "state_to_exposure",
    "exposure_to_driver",
    "driver_to_claim",
    "driver_to_financial",
    "demand",
    "supply",
    "competition",
    "customer",
    "financial",
    "other",
)
CAUSAL_EDGE_STATUS_RANK = {
    "deprecated": 0,
    "challenged": 1,
    "candidate": 2,
    "observed": 3,
    "supported": 4,
    "established": 5,
}
CONSTITUTION_RULES = (
    "price_cannot_modify_fundamental_claim",
    "news_cannot_modify_core_claim",
    "low_confidence_cannot_modify_current_state",
    "weak_signal_becomes_research_question",
    "state_slower_than_event",
    "driver_slower_than_state",
    "claim_slower_than_driver",
    "causal_slower_than_claim",
    "unsupported_causal_cannot_transmit",
    "unexplained_price_is_not_mispricing",
    "abnormal_change_scope_requires_review",
    "absence_is_not_counter_evidence",
    "related_entity_cannot_prove_issuer",
    "duplicate_news_cannot_version_claim",
    "new_causal_edge_starts_candidate",
    "unsupported_event_claim_jump",
    "financial_transmission_cannot_modify_base",
)
CHANGE_BUDGET = {
    "max_auto_claims": 1,
    "max_related_drivers": 2,
    "max_unrelated_drivers": 1,
    "max_auto_states": 2,
    "max_auto_base": 0,
    "max_auto_causal_edges": 1,
    "max_slow_layers": 2,
}
FUNDAMENTAL_CLAIM_TYPES = ("structural", "operating")
LOW_RELIABILITY = ("rumor", "opinion", "signal")
TRANSMITTABLE_EDGE_STATUSES = ("observed", "supported", "established")
CLAIM_STATUS_RANK = {
    "contradicted": 0,
    "challenged": 1,
    "unverified": 2,
    "emerging": 2,
    "background": 2,
    "partially_supported": 3,
    "strongly_supported": 4,
    "confirmed": 4,
    "closed": 2,
}
