"""Company exposure: the same industry/macro event does not hit every issuer equally.

Fixed path: State/Event → Company Exposure → Driver.
Never Event → Claim.
Related-entity evidence must pass Entity → Relationship → Exposure.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .claim_integrity import classify_source_relationship
from .types import EXPOSURE_TYPES


def related_entity_cannot_prove_issuer(evidence: dict[str, Any] | None, *, ticker: str, related_entities: list[dict[str, Any]] | None = None) -> bool:
    rel = classify_source_relationship(evidence, ticker=ticker, related_entities=related_entities)
    return rel == "related_entity_primary"


def infer_exposure(
    *,
    ticker: str,
    state_or_event: dict[str, Any],
    related_entities: list[dict[str, Any]] | None = None,
    evidence_rows: list[dict[str, Any]] | None = None,
    origin: str = "unknown",
) -> dict[str, Any] | None:
    symbol = str(ticker or "").upper()
    blob = " ".join(
        str(state_or_event.get(key) or "")
        for key in ("subject", "title", "statement", "name", "new_fact", "entities")
    ).lower()
    entity_names = []
    for item in related_entities or []:
        if isinstance(item, dict):
            entity_names.append(str(item.get("name") or item.get("ticker") or "").lower())
        else:
            entity_names.append(str(item).lower())
    mentions_issuer = symbol.lower() in blob
    mentions_related = any(name and name in blob for name in entity_names if name and name != symbol.lower())
    evidence_ids = [str(row.get("id") or row.get("evidence_id")) for row in (evidence_rows or []) if row.get("id") or row.get("evidence_id")]
    related_only = any(
        related_entity_cannot_prove_issuer(row, ticker=symbol, related_entities=related_entities)
        for row in (evidence_rows or [])
    ) or origin == "related_entity"
    if related_only and not mentions_issuer:
        return {
            "exposure_id": new_id("bexp"),
            "ticker": symbol,
            "state_or_event": state_or_event.get("event_id") or state_or_event.get("state_id") or state_or_event.get("state_key"),
            "exposure_type": "customer",
            "direction": str(state_or_event.get("direction") or "watch"),
            "magnitude": "unknown",
            "direct_or_indirect": "indirect",
            "evidence_ids": evidence_ids,
            "uncertainty": "high",
            "related_only": True,
            "can_affect_claim": False,
            "reason": "Related-entity evidence cannot directly prove an issuer fact or move a company Claim.",
        }
    if origin not in {"issuer_news", "issuer_primary", "company_state"} and not mentions_issuer and not mentions_related:
        return None
    exposure_type = "financial"
    if any(token in blob for token in ("customer", "hyperscaler", "meta", "google", "aws")):
        exposure_type = "customer"
    elif any(token in blob for token in ("supplier", "foundry", "tsmc")):
        exposure_type = "supplier"
    issuer_linked = origin in {"issuer_news", "issuer_primary", "company_state"} or mentions_issuer
    return {
        "exposure_id": new_id("bexp"),
        "ticker": symbol,
        "state_or_event": state_or_event.get("event_id") or state_or_event.get("state_id") or state_or_event.get("state_key") or compact_text(state_or_event.get("subject") or state_or_event.get("title") or "", 80),
        "exposure_type": exposure_type if exposure_type in EXPOSURE_TYPES else "financial",
        "direction": str(state_or_event.get("direction") or state_or_event.get("impact") or "watch"),
        "magnitude": str(state_or_event.get("magnitude") or ("medium" if issuer_linked else "unknown")),
        "direct_or_indirect": "direct" if issuer_linked else "indirect",
        "evidence_ids": evidence_ids,
        "uncertainty": "medium" if issuer_linked else "high",
        "related_only": False,
        "can_affect_claim": bool(issuer_linked and not related_only),
        "reason": "Issuer-linked exposure" if issuer_linked else "Indirect exposure pending issuer evidence",
    }


def normalize_exposure(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or raw.get("ticker") or "").upper()
    subject = compact_text(raw.get("subject") or symbol, 80) or symbol
    object_name = compact_text(raw.get("object_name") or raw.get("object") or raw.get("name") or "", 120)
    exposure_type = str(raw.get("exposure_type") or "financial")
    if exposure_type not in EXPOSURE_TYPES:
        exposure_type = "financial"
    return {
        "exposure_id": raw.get("exposure_id") or new_id("bexp"),
        "ticker": symbol,
        "subject": subject,
        "object_name": object_name,
        "state_or_event": raw.get("state_or_event") or raw.get("event_id") or raw.get("state_id"),
        "event_id": raw.get("event_id"),
        "state_id": raw.get("state_id"),
        "exposure_type": exposure_type,
        "direction": str(raw.get("direction") or "watch"),
        "magnitude": str(raw.get("magnitude") or "medium"),
        "direct_or_indirect": raw.get("direct_or_indirect") or "direct",
        "mechanism": compact_text(raw.get("mechanism") or raw.get("reason") or "", 240),
        "evidence_ids": [str(item) for item in (raw.get("evidence_ids") or []) if str(item).strip()],
        "uncertainty": raw.get("uncertainty") or "medium",
        "related_only": bool(raw.get("related_only")),
        "can_affect_claim": bool(raw.get("can_affect_claim", True)) and not raw.get("related_only"),
        "reason": compact_text(raw.get("reason") or raw.get("mechanism") or f"{subject} is exposed to {object_name}", 240),
        "related_driver_id": raw.get("related_driver_id"),
        "related_claim_id": raw.get("related_claim_id"),
    }


def relevant_exposures(
    *,
    event: dict[str, Any] | None,
    exposures: list[dict[str, Any]] | None,
    driver_ids: set[str] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    item = event or {}
    entities = {str(value).strip().lower() for value in (item.get("entities") or []) if str(value).strip()}
    event_type = str(item.get("event_type") or "").lower()
    blob = f"{item.get('title') or ''} {item.get('fact') or ''} {' '.join(entities)}".lower()
    wanted_types = set()
    if event_type in {"customer", "demand", "capex"} or any(ent in {"google", "meta", "openai", "anthropic"} for ent in entities):
        wanted_types.add("customer")
    if event_type in {"competition"} or "marvell" in entities:
        wanted_types.update({"competitive", "customer"})
    if event_type in {"supply"}:
        wanted_types.add("supplier")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in exposures or []:
        eid = str(row.get("exposure_id") or "")
        if not eid or eid in seen:
            continue
        text = " ".join(
            str(row.get(key) or "")
            for key in ("subject", "object_name", "reason", "mechanism", "exposure_type", "related_driver_id")
        ).lower()
        hit = False
        if row.get("related_driver_id") and str(row.get("related_driver_id")) in (driver_ids or set()):
            hit = True
        if str(row.get("exposure_type") or "") in wanted_types:
            hit = True
        if any(ent and len(ent) > 3 and ent in text for ent in entities):
            hit = True
        if any(token in text for token in ("asic", "hyperscaler", "custom silicon") if token in blob):
            hit = True
        if hit:
            seen.add(eid)
            out.append(row)
        if len(out) >= limit:
            break
    return out


def may_affect_company_claim(exposure: dict[str, Any] | None) -> bool:
    if not exposure:
        return False
    if exposure.get("related_only"):
        return False
    return bool(exposure.get("can_affect_claim")) and str(exposure.get("direct_or_indirect") or "") in {"direct", "indirect"}
