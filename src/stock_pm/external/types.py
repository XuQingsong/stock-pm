from __future__ import annotations

from typing import Any, TypedDict


SOURCE_TYPES = ("official", "independent_news", "industry", "aggregator", "macro", "market_data")
NEWS_WINDOW_DAYS = 30
TAVILY_SEARCH_BUDGET = 10
EXA_SEARCH_BUDGET = 10
QUERY_TYPES = (
    "company_official",
    "company_earnings",
    "company_news",
    "industry_news",
    "claim",
    "related_entity",
    "customer",
    "supplier",
    "macro",
    "fallback",
)
DISCOVERY_PROVIDERS = ("tavily", "exa", "duckduckgo", "google_cse")


class ExternalDocument(TypedDict, total=False):
    document_id: str
    provider: str
    source_type: str
    ticker: str | None
    title: str
    url: str
    source_domain: str
    published_at: str | None
    fetched_at: str
    author: str | None
    raw_text: str
    clean_text: str
    provider_score: float | None
    is_full_text: bool
    is_dated: bool
    is_primary_source: bool
    query: str
    query_type: str
    metadata: dict[str, Any]
    source_family: str
    source_tier: int
    canonical_url: str


class ProviderAudit(TypedDict, total=False):
    provider: str
    status: str
    query: str
    query_type: str
    hit_count: int
    usable_count: int
    high_quality_count: int
    full_text_count: int
    dated_count: int
    error: str | None
    latency_ms: int | None


def empty_provider_status(provider: str, *, status: str = "not_configured", error: str | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": status,
        "queries": [],
        "hit_count": 0,
        "usable_count": 0,
        "high_quality_count": 0,
        "full_text_count": 0,
        "dated_count": 0,
        "error": error,
    }
