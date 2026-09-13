"""Unified trusted-event model. Facts, media, and research stay separate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EVENT_TYPES = (
    "war_sanctions",
    "energy_supply",
    "sovereign_or_corporate_debt",
    "central_bank_rates",
    "inflation_employment",
    "gold_wti",
    "fx_usd",
    "vix_risk",
    "company_filing",
    "other",
)

CONTENT_TYPES = ("official_fact", "media_report", "research_opinion", "aggregator")
FACT_OR_OPINION = ("fact", "opinion")
SOURCE_TIERS = (1, 2, 3, 4)


@dataclass(slots=True)
class EventSource:
    source_id: str
    source_url: str
    canonical_url: str
    publisher: str
    source_tier: int
    content_type: str
    fact_or_opinion: str
    primary_or_secondary: str
    title: str
    published_at: str | None = None
    first_seen_at: str | None = None
    event_id: str | None = None
    document_role: str | None = None
    evidence_role: str = "event_fact"
    last_fetched_at: str | None = None
    body_source: str | None = None
    fetch_error: str | None = None
    filing_items: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "publisher": self.publisher,
            "source_tier": self.source_tier,
            "content_type": self.content_type,
            "fact_or_opinion": self.fact_or_opinion,
            "primary_or_secondary": self.primary_or_secondary,
            "title": self.title,
            "published_at": self.published_at,
            "first_seen_at": self.first_seen_at,
            "event_id": self.event_id,
            "document_role": self.document_role,
            "evidence_role": self.evidence_role,
            "last_fetched_at": self.last_fetched_at,
            "body_source": self.body_source,
            "fetch_error": self.fetch_error,
            "filing_items": list(self.filing_items),
        }


@dataclass(slots=True)
class EventClaim:
    claim_id: str
    text: str
    polarity: str
    source_id: str
    status: str = "open"
    source_url: str = ""
    publisher: str = ""
    valid_from: str | None = None
    observed_at: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    excerpt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "polarity": self.polarity,
            "source_id": self.source_id,
            "status": self.status,
            "source_url": self.source_url,
            "publisher": self.publisher,
            "valid_from": self.valid_from,
            "observed_at": self.observed_at,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "excerpt": self.excerpt,
        }


@dataclass(slots=True)
class EventDocument:
    """A discovered document. Never treated as a priced forecast."""

    title: str
    url: str
    publisher: str
    published_at: str | None
    event_type: str
    entities: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    body: str = ""
    provider: str = "official"
    status: str = "active"
    etag: str | None = None
    last_modified: str | None = None
    document_role: str | None = None
    evidence_role: str = "event_fact"
    supersedes_url: str | None = None
    last_fetched_at: str | None = None
    body_source: str = ""
    fetch_error: str | None = None
    filing_items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TrustedEvent:
    event_id: str
    canonical_title: str
    event_type: str
    entities: list[str]
    countries: list[str]
    event_time: str | None
    published_at: str | None
    first_seen_at: str
    updated_at: str
    sources: list[EventSource]
    claims: list[EventClaim]
    dedupe_group: str
    status: str
    freshness: str
    severity: str
    scope: str
    duration: str | None
    invalidation: str | None
    timeline: list[dict[str, Any]] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "canonical_title": self.canonical_title,
            "event_type": self.event_type,
            "entities": list(self.entities),
            "countries": list(self.countries),
            "event_time": self.event_time,
            "published_at": self.published_at,
            "first_seen_at": self.first_seen_at,
            "updated_at": self.updated_at,
            "sources": [row.as_dict() for row in self.sources],
            "claims": [row.as_dict() for row in self.claims],
            "timeline": [dict(row) for row in self.timeline],
            "dedupe_group": self.dedupe_group,
            "status": self.status,
            "freshness": self.freshness,
            "severity": self.severity,
            "scope": self.scope,
            "duration": self.duration,
            "invalidation": self.invalidation,
            "analysis": dict(self.analysis),
            "coverage": dict(self.coverage),
        }
