"""Event objects. Not every news item is an Event."""

from __future__ import annotations

import hashlib
from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .knowledge import classify_information
from .limits import limit_words
from .types import EVENT_TYPES, KNOWLEDGE_LAYERS


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def make_event_fingerprint(row: dict[str, Any]) -> str:
    blob = "|".join(
        [
            str(row.get("event_type") or ""),
            str(row.get("subject") or ""),
            str(row.get("event_date") or "")[:10],
            str(row.get("source_url") or row.get("url") or ""),
            compact_text(row.get("title") or row.get("new_fact") or "", 80).lower(),
        ]
    )
    return "bevfp_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def infer_event_type(row: dict[str, Any]) -> str:
    blob = f"{row.get('title') or ''} {row.get('new_fact') or ''} {row.get('fact') or ''}".lower()
    mapping = (
        ("earnings", ("earnings", "eps", "10-q", "quarter")),
        ("guidance", ("guidance", "outlook", "raise", "cut")),
        ("capex", ("capex", "capital expenditure", "spend")),
        ("product", ("launch", "iphone", "product cycle")),
        ("regulation", ("regulator", "doj", "dma", "antitrust")),
        ("competition", ("competitor", "share loss", "internal asic")),
        ("macro", ("fed", "rates", "cpi", "tariff")),
        ("mna", ("acquire", "merger", "deal")),
        ("litigation", ("lawsuit", "settlement")),
        ("customer", ("customer", "hyperscaler", "design win")),
        ("supply", ("supplier", "foundry", "capacity")),
    )
    for event_type, tokens in mapping:
        if any(token in blob for token in tokens):
            return event_type
    return "other"


def build_event(
    raw: dict[str, Any],
    *,
    ticker: str,
    related_entities: list[dict[str, Any]] | None = None,
    drivers: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    title = compact_text(raw.get("title") or raw.get("new_fact") or raw.get("fact") or "", 160)
    if not title:
        return None
    classified = classify_information(
        raw,
        ticker=ticker,
        related_entities=related_entities,
        drivers=drivers,
        claims=claims,
    )
    layer = classified["layer"]
    if layer not in KNOWLEDGE_LAYERS:
        layer = "context"
    event_type = str(raw.get("event_type") or infer_event_type(raw))
    if event_type not in EVENT_TYPES:
        event_type = "other"
    fingerprint = make_event_fingerprint({**raw, "event_type": event_type, "subject": raw.get("subject") or title, "title": title})
    for prior in existing or []:
        if prior.get("fingerprint") == fingerprint:
            return {**prior, "duplicate": True, "match_action": "duplicate"}
    evidence_ids = []
    for item in raw.get("evidence_ids") or ([raw.get("evidence_id")] if raw.get("evidence_id") else []):
        key = str(item or "").strip()
        if key and key not in evidence_ids:
            evidence_ids.append(key)
    novelty = str(raw.get("novelty") or "new")
    return {
        "event_id": new_id("bev"),
        "ticker": str(ticker).upper(),
        "event_type": event_type,
        "subject": compact_text(raw.get("subject") or title, 80),
        "title": title,
        "event_date": raw.get("event_date") or raw.get("published_at") or raw.get("source_time"),
        "entities": [str(item) for item in (raw.get("entities") or raw.get("related_entities") or []) if str(item).strip()],
        "evidence_ids": evidence_ids,
        "confidence": raw.get("confidence") or classified.get("fact_reliability"),
        "materiality": layer,
        "novelty": novelty,
        "source_quality": classified["source_quality"],
        "fact_reliability": classified["fact_reliability"],
        "decision_targets": classified["decision_targets"],
        "affected_states": list(raw.get("affected_states") or []),
        "affected_drivers": list(raw.get("affected_drivers") or []),
        "affected_claims": list(raw.get("affected_claims") or []),
        "transmission": _as_dict(raw.get("transmission")),
        "financial_impact": _as_dict(raw.get("financial_impact")),
        "scenario_impact": _as_dict(raw.get("scenario_impact")),
        "fingerprint": fingerprint,
        "duplicate": False,
        "url": raw.get("url") or raw.get("source_url"),
        "reason": limit_words(compact_text(raw.get("reason") or "", 400), 40),
    }


def is_material_event(event: dict[str, Any] | None) -> bool:
    return str((event or {}).get("materiality") or "") == "material"
