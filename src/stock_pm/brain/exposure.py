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


def may_affect_company_claim(exposure: dict[str, Any] | None) -> bool:
    if not exposure:
        return False
    if exposure.get("related_only"):
        return False
    return bool(exposure.get("can_affect_claim")) and str(exposure.get("direct_or_indirect") or "") in {"direct", "indirect"}
