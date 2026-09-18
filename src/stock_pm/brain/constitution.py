"""Brain Constitution: deterministic write rules. Not prompt text."""

from __future__ import annotations

from typing import Any

from .causal import transmission_stop_reason
from .claim_integrity import news_is_duplicate
from .exposure import related_entity_cannot_prove_issuer
from .hysteresis import next_claim_status
from .knowledge import fact_reliability
from .shadow import should_enter_shadow
from .types import FUNDAMENTAL_CLAIM_TYPES, LOW_RELIABILITY


def _payload(proposal: dict[str, Any]) -> dict[str, Any]:
    raw = proposal.get("to_payload")
    return dict(raw) if isinstance(raw, dict) else {}


def _source_kind(proposal: dict[str, Any]) -> str:
    return str(proposal.get("source_kind") or proposal.get("kind") or "news").lower()


def _reliability(proposal: dict[str, Any]) -> str:
    return str(proposal.get("fact_reliability") or fact_reliability(proposal) or "")


def constitution_violations(proposal: dict[str, Any], *, brain: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Return rule hits. Empty means the proposal is constitutionally allowed (budget still applies)."""
    context = brain or {}
    target = str(proposal.get("object_type") or "")
    source = _source_kind(proposal)
    payload = _payload(proposal)
    current = proposal.get("from_payload") if isinstance(proposal.get("from_payload"), dict) else {}
    hits: list[dict[str, str]] = []

    if source == "price" and target in {"claim", "core_claim"}:
        claim_type = str(payload.get("claim_type") or current.get("claim_type") or "operating")
        if claim_type in FUNDAMENTAL_CLAIM_TYPES or str(payload.get("is_core") or current.get("is_core") or "").lower() in {"1", "true"}:
            hits.append({"rule": "price_cannot_modify_fundamental_claim", "reason": "Price cannot directly modify a Fundamental Claim."})
        if "mispricing" in f"{payload.get('statement') or ''} {proposal.get('reason') or ''}".lower():
            hits.append({"rule": "unexplained_price_is_not_mispricing", "reason": "Unexplained price move is not mispricing."})

    if source in {"news", "event"} and target in {"claim", "core_claim"}:
        changing_status = "status" in payload and str(payload.get("status") or "") != str(current.get("status") or "")
        changing_statement = "statement" in payload and str(payload.get("statement") or "") != str(current.get("statement") or "")
        if current.get("is_core") or target == "core_claim" or payload.get("is_core"):
            if changing_status or changing_statement:
                hits.append({"rule": "news_cannot_modify_core_claim", "reason": "News or Event cannot directly modify a Core Claim."})

    conclusion_targets = {
        "state",
        "company_state",
        "industry_state",
        "macro_state",
        "driver",
        "value_driver",
        "claim",
        "core_claim",
        "scenario",
        "financial_impact",
    }

    if target in {"state", "company_state", "industry_state", "macro_state"}:
        confidence = str(proposal.get("confidence") or payload.get("confidence") or current.get("confidence") or "")
        if should_enter_shadow(proposal) or _reliability(proposal) in LOW_RELIABILITY or confidence == "low":
            hits.append({"rule": "low_confidence_cannot_modify_current_state", "reason": "Low-confidence information must enter Shadow State."})
        if source in {"news", "event", "signal", "rumor", "price"}:
            hits.append({"rule": "state_slower_than_event", "reason": "State must change slower than Event."})

    if target in {"driver", "value_driver"} and source in {"news", "event", "signal", "rumor", "price"}:
        hits.append({"rule": "driver_slower_than_state", "reason": "Value Driver must change slower than State."})

    if target in conclusion_targets and is_weak_signal(proposal):
        hits.append({"rule": "weak_signal_becomes_research_question", "reason": "Weak signal produces a Research Question, not a conclusion."})

    if target in {"claim", "core_claim"} and source in {"news", "event", "signal", "rumor"}:
        inertia = next_claim_status(
            current,
            payload.get("status"),
            independent_counter_count=int(proposal.get("independent_counter_count") or 0),
            source_kind=source,
        )
        proposed_status = str(payload.get("status") or "")
        current_status = str(current.get("status") or "")
        if proposed_status and proposed_status != current_status and (proposed_status != inertia["status"] or not inertia["changed"]):
            hits.append({"rule": "claim_slower_than_driver", "reason": "Core Claim cannot jump on a single item."})

    if target in {"causal_edge", "causal_relationship"} and source in {"news", "event", "signal", "price"}:
        new_status = str(payload.get("status") or "candidate")
        if new_status in {"supported", "established"}:
            hits.append({"rule": "causal_slower_than_claim", "reason": "Causal Graph cannot jump to established from a single event."})

    edges = list(proposal.get("causal_edges") or payload.get("causal_edges") or context.get("causal_edges") or [])
    if target in {"claim", "core_claim", "driver", "value_driver", "financial_impact", "scenario"}:
        stopped = transmission_stop_reason(edges)
        if stopped:
            hits.append({"rule": "unsupported_causal_cannot_transmit", "reason": stopped})

    if source == "price" and target in {"claim", "core_claim", "driver", "value_driver"}:
        if not proposal.get("fundamental_evidence_ids"):
            hits.append({"rule": "unexplained_price_is_not_mispricing", "reason": "Price without fundamental evidence cannot rewrite investment reasoning."})

    evidence_ids = [str(item) for item in (proposal.get("evidence_ids") or payload.get("evidence_ids") or []) if str(item).strip()]
    reason = str(proposal.get("reason") or payload.get("reason") or "").lower()
    oppose = str(payload.get("status") or "").lower() in {"challenged", "contradicted"} or str(payload.get("direction") or "") == "oppose"
    if oppose and not evidence_ids:
        hits.append({"rule": "absence_is_not_counter_evidence", "reason": "Absence of evidence is not counter evidence."})
    if oppose and any(token in reason for token in ("no evidence", "lack of evidence", "hasn't been", "not reported", "absence of")):
        hits.append({"rule": "absence_is_not_counter_evidence", "reason": "Absence of evidence is not counter evidence."})

    evidence_row = proposal.get("evidence") if isinstance(proposal.get("evidence"), dict) else None
    ticker = str(proposal.get("ticker") or (brain or {}).get("ticker") or "")
    if evidence_row and related_entity_cannot_prove_issuer(evidence_row, ticker=ticker, related_entities=context.get("related_entities")):
        if target in {"claim", "core_claim", "state", "company_state"}:
            hits.append({"rule": "related_entity_cannot_prove_issuer", "reason": "Related-company information cannot directly prove an issuer fact."})

    if proposal.get("duplicate") or (source in {"news", "event"} and target in {"claim", "core_claim"} and payload.get("new_version")):
        facts = [str(item) for item in (context.get("existing_facts") or [])]
        hit = {"title": proposal.get("title") or payload.get("title"), "new_fact": proposal.get("new_fact") or payload.get("statement")}
        if proposal.get("duplicate") or (facts and news_is_duplicate(hit, facts)):
            hits.append({"rule": "duplicate_news_cannot_version_claim", "reason": "Duplicate news cannot create a new Claim version."})

    return hits


def is_weak_signal(observation: dict[str, Any] | None) -> bool:
    item = observation or {}
    reliability = str(item.get("fact_reliability") or fact_reliability(item))
    return reliability in LOW_RELIABILITY or str(item.get("confidence") or "") == "low" or should_enter_shadow(item)
