"""Merge multi-source reports of one event; keep distinct events apart."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .policy import document_to_source, sanitize_untrusted
from .types import EventClaim, EventDocument, EventSource, TrustedEvent


STOP = frozenset(
    "the a an of to for in on and or as by with from after before over under about vs versus".split()
)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", (text or "").lower())
    return {word for word in words if word not in STOP}


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def same_event(left: EventDocument, right: EventDocument) -> bool:
    if left.event_type != right.event_type:
        return False
    left_countries = {item.upper() for item in left.countries}
    right_countries = {item.upper() for item in right.countries}
    if left_countries and right_countries and not left_countries & right_countries:
        return False
    left_geo = left_countries - {"US", "USA"}
    right_geo = right_countries - {"US", "USA"}
    if left_geo and right_geo and not left_geo & right_geo:
        return False
    left_entities = {item.lower() for item in left.entities}
    right_entities = {item.lower() for item in right.entities}
    shared = left_entities & right_entities
    title_score = _overlap(_tokens(left.title), _tokens(right.title))
    entity_score = _overlap(left_entities, right_entities)
    claim_score = _overlap(_tokens(" ".join(left.claims)), _tokens(" ".join(right.claims)))
    # Curated entity fingerprints beat noisy titles. Require enough overlap
    # so "Iran oil sanctions" does not swallow "Russia oil sanctions".
    if left_entities - right_entities and right_entities - left_entities and entity_score < 0.66:
        return False
    if len(shared) >= 2 and entity_score >= 0.66:
        return True
    if title_score >= 0.72 and entity_score >= 0.66:
        return True
    if entity_score >= 0.6 and claim_score >= 0.4:
        return True
    return False


def _stable_id(docs: list[EventDocument]) -> str:
    shared = set(docs[0].entities)
    for row in docs[1:]:
        shared &= set(row.entities)
    material = f"{docs[0].event_type}|{'/'.join(sorted(shared or docs[0].entities))}|{'/'.join(sorted(docs[0].countries))}"
    return "evt_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def cluster_documents(docs: list[EventDocument]) -> list[list[EventDocument]]:
    clusters: list[list[EventDocument]] = []
    for doc in docs:
        placed = False
        for cluster in clusters:
            if any(same_event(doc, existing) for existing in cluster):
                cluster.append(doc)
                placed = True
                break
        if not placed:
            clusters.append([doc])
    return clusters


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _severity(event_type: str) -> str:
    if event_type in {"war_sanctions", "energy_supply", "sovereign_or_corporate_debt"}:
        return "high"
    if event_type in {"central_bank_rates", "inflation_employment", "vix_risk"}:
        return "watch"
    return "info"


def _duration(event_type: str) -> str:
    if event_type in {"war_sanctions", "energy_supply"}:
        return "days_to_weeks"
    if event_type in {"central_bank_rates", "inflation_employment"}:
        return "weeks_to_months"
    if event_type == "vix_risk":
        return "session_to_days"
    return "unspecified"


def _status(docs: list[EventDocument]) -> str:
    if any(row.status == "revoked" for row in docs):
        return "revoked"
    if any(row.status == "updated" for row in docs):
        return "updated"
    return "active"


def build_events(docs: list[EventDocument], *, seen_at: str | None = None) -> list[TrustedEvent]:
    stamp = seen_at or _now()
    events: list[TrustedEvent] = []
    for cluster in cluster_documents(docs):
        official = [row for row in cluster if row.provider == "official"]
        lead = official[0] if official else cluster[0]
        event_id = _stable_id(cluster)
        sources = []
        claims = []
        seen_urls: set[str] = set()
        for doc in cluster:
            payload = document_to_source(doc, seen_at=stamp)
            if payload["canonical_url"] in seen_urls:
                continue
            seen_urls.add(str(payload["canonical_url"]))
            source = EventSource(
                source_id=str(payload["source_id"]),
                source_url=str(payload["source_url"]),
                canonical_url=str(payload["canonical_url"]),
                publisher=str(payload["publisher"]),
                source_tier=int(payload["source_tier"]),
                content_type=str(payload["content_type"]),
                fact_or_opinion=str(payload["fact_or_opinion"]),
                primary_or_secondary=str(payload["primary_or_secondary"]),
                title=str(payload["title"]),
                published_at=payload.get("published_at"),  # type: ignore[arg-type]
                first_seen_at=payload.get("first_seen_at"),  # type: ignore[arg-type]
                event_id=event_id,
            )
            sources.append(source)
            for index, claim in enumerate(doc.claims or [doc.title]):
                polarity = "revokes" if doc.status == "revoked" else ("updates" if doc.status == "updated" else "supports")
                if "contradict" in sanitize_untrusted(claim).lower() or "并非" in claim or "否认" in claim:
                    polarity = "contradicts"
                claims.append(
                    EventClaim(
                        claim_id=f"{source.source_id}_{index}",
                        text=sanitize_untrusted(claim),
                        polarity=polarity,
                        source_id=source.source_id,
                    )
                )
        times = [row.published_at for row in cluster if row.published_at]
        events.append(
            TrustedEvent(
                event_id=event_id,
                canonical_title=lead.title,
                event_type=lead.event_type,
                entities=sorted({item for row in cluster for item in row.entities}),
                countries=sorted({item for row in cluster for item in row.countries}),
                event_time=min(times) if times else lead.published_at,
                published_at=min(times) if times else lead.published_at,
                first_seen_at=stamp,
                updated_at=max(times) if times else stamp,
                sources=sources,
                claims=claims,
                dedupe_group=event_id,
                status=_status(cluster),
                freshness="fresh",
                severity=_severity(lead.event_type),
                scope="market",
                duration=_duration(lead.event_type),
                invalidation="若官方原文撤销、制裁清单更新或供应中断被证伪，则该事件影响链失效",
            )
        )
    return events
