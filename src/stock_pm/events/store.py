"""Optional Postgres persistence. In-memory service remains the analyzer."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .types import TrustedEvent


UPSERT_EVENT = """
INSERT INTO trusted_events (
    event_id, canonical_title, event_type, entities, countries, event_time,
    published_at, first_seen_at, updated_at, dedupe_group, status, freshness,
    severity, scope, duration, invalidation, coverage, analysis, raw
) VALUES (
    %(event_id)s, %(canonical_title)s, %(event_type)s, %(entities)s, %(countries)s,
    %(event_time)s, %(published_at)s, %(first_seen_at)s, %(updated_at)s,
    %(dedupe_group)s, %(status)s, %(freshness)s, %(severity)s, %(scope)s,
    %(duration)s, %(invalidation)s, %(coverage)s, %(analysis)s, %(raw)s
)
ON CONFLICT (event_id) DO UPDATE SET
    canonical_title = EXCLUDED.canonical_title,
    updated_at = EXCLUDED.updated_at,
    status = EXCLUDED.status,
    freshness = EXCLUDED.freshness,
    analysis = EXCLUDED.analysis,
    coverage = EXCLUDED.coverage
"""

UPSERT_SOURCE = """
INSERT INTO trusted_event_sources (
    source_id, event_id, source_url, canonical_url, publisher, source_tier,
    content_type, fact_or_opinion, primary_or_secondary, title, published_at, first_seen_at
) VALUES (
    %(source_id)s, %(event_id)s, %(source_url)s, %(canonical_url)s, %(publisher)s,
    %(source_tier)s, %(content_type)s, %(fact_or_opinion)s, %(primary_or_secondary)s,
    %(title)s, %(published_at)s, %(first_seen_at)s
)
ON CONFLICT (canonical_url) DO UPDATE SET
    title = EXCLUDED.title,
    published_at = EXCLUDED.published_at
"""

UPSERT_CLAIM = """
INSERT INTO trusted_event_claims (claim_id, event_id, source_id, text, polarity, status)
VALUES (%(claim_id)s, %(event_id)s, %(source_id)s, %(text)s, %(polarity)s, %(status)s)
ON CONFLICT (claim_id) DO UPDATE SET text = EXCLUDED.text, polarity = EXCLUDED.polarity
"""

UPSERT_CURSOR = """
INSERT INTO event_job_cursors (provider, last_success, last_attempt, status, reason_code, item_count)
VALUES (%(provider)s, %(last_success)s, %(last_attempt)s, %(status)s, %(reason_code)s, %(item_count)s)
ON CONFLICT (provider) DO UPDATE SET
    last_success = EXCLUDED.last_success,
    last_attempt = EXCLUDED.last_attempt,
    status = EXCLUDED.status,
    reason_code = EXCLUDED.reason_code,
    item_count = EXCLUDED.item_count
"""


def persist_events(conn, events: list[TrustedEvent], coverage: dict[str, Any] | None = None) -> int:
    written = 0
    for event in events:
        payload = event.as_dict()
        conn.execute(
            UPSERT_EVENT,
            {
                **payload,
                "entities": Jsonb(payload["entities"]),
                "countries": Jsonb(payload["countries"]),
                "coverage": Jsonb(coverage or payload.get("coverage") or {}),
                "analysis": Jsonb(payload.get("analysis") or {}),
                "raw": Jsonb({"source_count": len(event.sources)}),
            },
        )
        for source in event.sources:
            conn.execute(UPSERT_SOURCE, {**source.as_dict(), "event_id": event.event_id})
        for claim in event.claims:
            conn.execute(
                UPSERT_CLAIM,
                {
                    "claim_id": claim.claim_id,
                    "event_id": event.event_id,
                    "source_id": claim.source_id,
                    "text": claim.text,
                    "polarity": claim.polarity,
                    "status": claim.status,
                },
            )
        written += 1
    return written


def persist_cursor(conn, provider: str, *, status: str, reason_code: str | None, item_count: int, stamp: str) -> None:
    conn.execute(
        UPSERT_CURSOR,
        {
            "provider": provider,
            "last_success": stamp if status == "ok" else None,
            "last_attempt": stamp,
            "status": status,
            "reason_code": reason_code,
            "item_count": item_count,
        },
    )
