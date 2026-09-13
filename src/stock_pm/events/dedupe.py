"""Merge multi-source reports of one event; keep distinct events apart."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from .evidence import infer_phase, publisher_key, source_metrics
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


def _published_day(doc: EventDocument):
    raw = doc.published_at
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def same_event(left: EventDocument, right: EventDocument) -> bool:
    if left.event_type != right.event_type:
        return False
    left_role = getattr(left, "evidence_role", "event_fact") or "event_fact"
    right_role = getattr(right, "evidence_role", "event_fact") or "event_fact"
    if left_role != right_role and "regime_catalog" in {left_role, right_role}:
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
    left_day = _published_day(left)
    right_day = _published_day(right)
    evolving = {left.status, right.status} & {"updated", "revoked"}
    if left_day and right_day and abs((left_day - right_day).days) > 45 and not evolving:
        return False
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


def _timeline_what(status: str, polarity: str, phase: str | None = None) -> str:
    from .evidence import PHASE_LABELS

    label = PHASE_LABELS.get(phase or "", "")
    if polarity == "revokes" or status == "revoked":
        return "后续原文撤销或否定先前表述，刷新 What changes，不新开事件"
    if polarity == "contradicts":
        return "同一 as-of 窗口内不同发布方对同一 claim 冲突，降低当前置信度"
    if polarity == "supersedes" or status == "superseded":
        if label:
            return f"{label}：后续官方预测替代先前基线，旧预测留在时间线，不作为当前冲突"
        return "后续官方预测替代先前基线，旧预测留在时间线，不作为当前冲突"
    if polarity == "updates" or status == "updated":
        return "同一事件补充文档进入时间线，不视为独立多源确认，也不重复叠加一条新方向"
    if label:
        return f"纳入同一事件时间线 · {label}"
    return "纳入同一事件时间线"


def _claim_polarity(doc: EventDocument, claim: str) -> str:
    text = sanitize_untrusted(claim)
    role = doc.document_role or ""
    if doc.evidence_role == "regime_catalog" or role == "regime_catalog":
        return "background"
    if doc.status == "revoked":
        return "revokes"
    sequential = role == "forecast_update" or bool(doc.supersedes_url) or doc.status == "updated"
    if sequential and role == "forecast_update":
        return "supersedes" if doc.supersedes_url or doc.status == "updated" else "supports"
    if "contradict" in text.lower() or "否认" in text or ("并非" in text and not sequential):
        return "contradicts"
    if doc.status == "updated" or role in {"minutes", "projections"}:
        return "updates"
    return "supports"


def _apply_supersession(claims: list[EventClaim], sources: list[EventSource], docs_by_url: dict[str, EventDocument]) -> None:
    by_id = {row.source_id: row for row in sources}

    def published(claim: EventClaim) -> str:
        source = by_id.get(claim.source_id)
        return str((source.published_at if source else None) or claim.observed_at or "")

    groups: dict[str, list[EventClaim]] = {}
    for claim in claims:
        source = by_id.get(claim.source_id)
        key = publisher_key(claim.publisher, source.source_url if source else "")
        groups.setdefault(key, []).append(claim)
    for rows in groups.values():
        rows.sort(key=published)
        forecast_chain = [
            claim
            for claim in rows
            if (by_id.get(claim.source_id) and by_id[claim.source_id].document_role == "forecast_update")
            or claim.polarity == "supersedes"
        ]
        for index, later in enumerate(forecast_chain):
            source = by_id.get(later.source_id)
            later.observed_at = published(later) or later.observed_at
            later.valid_from = later.observed_at
            doc = docs_by_url.get(later.source_url)
            prev = None
            if doc and doc.supersedes_url:
                prev = next((row for row in forecast_chain if row.source_url == doc.supersedes_url), None)
            if prev is None and index > 0:
                prev = forecast_chain[index - 1]
            if prev is None or prev.claim_id == later.claim_id:
                later.status = "current"
                continue
            prev.status = "superseded"
            prev.superseded_by = later.claim_id
            later.supersedes = prev.claim_id
            later.polarity = "supersedes"
            later.status = "current"
        for claim in rows:
            if not claim.observed_at:
                claim.observed_at = published(claim) or None
            if not claim.valid_from:
                claim.valid_from = claim.observed_at
            if claim.status == "open" and claim.polarity != "revokes":
                claim.status = "current"


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
                document_role=payload.get("document_role"),  # type: ignore[arg-type]
                evidence_role=str(payload.get("evidence_role") or "event_fact"),
            )
            sources.append(source)
            for index, claim in enumerate(doc.claims or [doc.title]):
                text = sanitize_untrusted(claim)
                claims.append(
                    EventClaim(
                        claim_id=f"{source.source_id}_{index}",
                        text=text,
                        polarity=_claim_polarity(doc, text),
                        source_id=source.source_id,
                        source_url=source.source_url,
                        publisher=source.publisher,
                        valid_from=doc.published_at,
                        observed_at=doc.published_at,
                        excerpt=sanitize_untrusted(doc.body or ""),
                    )
                )
        docs_by_url = {row.url: row for row in cluster}
        _apply_supersession(claims, sources, docs_by_url)
        times = [row.published_at for row in cluster if row.published_at]
        event_status = _status(cluster)
        timeline = []
        for claim in claims:
            source = next((row for row in sources if row.source_id == claim.source_id), None)
            phase = infer_phase(f"{claim.text} {source.title if source else ''}")
            entry_status = claim.status if claim.status in {"superseded", "current"} else (
                "revoked"
                if claim.polarity == "revokes"
                else ("updated" if claim.polarity in {"updates", "supersedes"} else "active")
            )
            timeline.append(
                {
                    "event_time": source.published_at if source else claim.observed_at,
                    "valid_from": claim.valid_from,
                    "observed_at": claim.observed_at,
                    "supersedes": claim.supersedes,
                    "status": entry_status,
                    "polarity": claim.polarity,
                    "phase": phase,
                    "document_role": source.document_role if source else None,
                    "publisher": claim.publisher,
                    "source_url": claim.source_url,
                    "claim": claim.text,
                    "what_changes": _timeline_what(entry_status, claim.polarity, phase),
                }
            )
        timeline.sort(key=lambda row: (row.get("event_time") or "", row.get("source_url") or ""))
        metrics = source_metrics(sources, claims)
        fact_docs = [row for row in cluster if (row.evidence_role or "event_fact") != "regime_catalog"]
        lead = next((row for row in official if (row.evidence_role or "event_fact") != "regime_catalog"), lead)
        events.append(
            TrustedEvent(
                event_id=event_id,
                canonical_title=lead.title,
                event_type=lead.event_type,
                entities=sorted({item for row in fact_docs for item in row.entities} or {item for row in cluster for item in row.entities}),
                countries=sorted({item for row in cluster for item in row.countries}),
                event_time=min(times) if times else lead.published_at,
                published_at=min(times) if times else lead.published_at,
                first_seen_at=stamp,
                updated_at=max(times) if times else stamp,
                sources=sources,
                claims=claims,
                timeline=timeline,
                dedupe_group=event_id,
                status=event_status,
                freshness="fresh",
                severity=_severity(lead.event_type),
                scope="market",
                duration=_duration(lead.event_type),
                invalidation=(
                    "若 FOMC 后续声明或会议记录撤回该会议的利率事实，则该观察失效"
                    if lead.event_type == "central_bank_rates"
                    else "若后续官方原文撤回最新预测或海峡通行事实再次反转，则该事件影响链失效"
                ),
                coverage=metrics,
            )
        )
    return events
