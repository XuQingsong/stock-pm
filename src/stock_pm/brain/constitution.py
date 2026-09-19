"""Brain Constitution: deterministic write rules. Not prompt text."""

from __future__ import annotations

from typing import Any

from .causal import coerce_causal_edges, next_edge_status, shortest_path, transmission_stop_reason
from .claim_integrity import news_is_duplicate
from .exposure import related_entity_cannot_prove_issuer
from .hysteresis import next_claim_status
from .knowledge import fact_reliability
from .shadow import should_enter_shadow
from .divergence import price_as_evidence_forbidden
from .types import FUNDAMENTAL_CLAIM_TYPES, INVESTMENT_DOWNSTREAM, LOW_RELIABILITY


def _payload(proposal: dict[str, Any]) -> dict[str, Any]:
    raw = proposal.get("to_payload")
    return dict(raw) if isinstance(raw, dict) else {}


def _source_kind(proposal: dict[str, Any]) -> str:
    return str(proposal.get("source_kind") or proposal.get("kind") or "news").lower()


def _reliability(proposal: dict[str, Any]) -> str:
    return str(proposal.get("fact_reliability") or fact_reliability(proposal) or "")


_STATEMENT_FIELDS = (
    "statement",
    "current_state",
    "status",
    "direction",
    "name",
    "title",
    "qualitative_state",
)


def _evidence_only_update(current: dict[str, Any] | None, payload: dict[str, Any] | None) -> bool:
    """Evidence / confidence / strength accumulation is allowed; statement jumps are not."""
    now = current or {}
    nxt = payload or {}
    if not nxt:
        return False
    for field in _STATEMENT_FIELDS:
        if field in nxt and str(nxt.get(field) or "") != str(now.get(field) or ""):
            return False
    allowed = {
        "evidence_ids",
        "supporting_evidence_ids",
        "opposing_evidence_ids",
        "support_strength",
        "counter_strength",
        "support_trend",
        "counter_trend",
        "uncertainty",
        "confidence",
        "last_material_change",
        "last_reviewed_at",
        "reasoning",
    }
    extra = {
        key
        for key in nxt
        if key not in allowed
        and key
        not in {
            "object_id",
            "ticker",
            "canonical_key",
            "state_id",
            "driver_id",
            "claim_id",
            "source_kind",
            "fact_reliability",
            "reason",
        }
    }
    if extra:
        return False
    return any(key in nxt for key in allowed)


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

    if source == "price" and target in {"state", "company_state", "industry_state", "macro_state"}:
        hits.append({"rule": "price_cannot_modify_fundamental_state", "reason": "Price cannot directly modify Fundamental State."})

    if target in {
        "market_attention",
        "expectation",
        "expectation_state",
        "market_driver",
        "market_driver_hypothesis",
        "price_reaction",
        "price_fundamental_divergence",
        "price_feedback",
    }:
        blob = f"{payload.get('statement') or ''} {payload.get('hypothesis') or ''} {proposal.get('reason') or ''} {payload.get('conclusion') or ''} {payload.get('alignment') or ''}".lower()
        if "mispricing" in blob:
            hits.append({"rule": "unexplained_price_is_not_mispricing", "reason": "Unexplained price move is not mispricing."})

    if target in {"market_driver_hypothesis", "market_driver"}:
        requested = str(payload.get("status") or "")
        if requested in {"established", "confirmed", "fact"} or payload.get("is_fact") is True:
            hits.append({"rule": "market_hypothesis_is_not_fact", "reason": "A market driver hypothesis stays a hypothesis, not a fact."})

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
        if source in {"news", "event", "signal", "rumor", "price"} and not _evidence_only_update(current, payload):
            hits.append({"rule": "state_slower_than_event", "reason": "State must change slower than Event."})

    if target in {"driver", "value_driver"} and source in {"news", "event", "signal", "rumor", "price"}:
        if not _evidence_only_update(current, payload):
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

    if source == "price" and target in {"causal_edge", "causal_relationship"}:
        requested_edge = str(payload.get("status") or payload.get("requested_status") or current.get("status") or "candidate")
        if requested_edge in {"supported", "established"}:
            hits.append(
                {
                    "rule": "price_cannot_create_established_causal_edge",
                    "reason": "Price cannot create or promote an established causal edge.",
                }
            )

    if target in {"causal_edge", "causal_relationship"}:
        requested = str(payload.get("status") or payload.get("requested_status") or current.get("status") or "candidate")
        existing = None
        for edge in coerce_causal_edges(context.get("causal_edges") or []):
            if str(edge.get("edge_id") or "") == str(proposal.get("object_id") or "") or (
                str(edge.get("from_node") or "") == str(payload.get("from_node") or current.get("from_node") or "")
                and str(edge.get("to_node") or "") == str(payload.get("to_node") or current.get("to_node") or "")
            ):
                existing = edge
                break
        is_new = existing is None
        if is_new and requested != "candidate":
            hits.append({"rule": "new_causal_edge_starts_candidate", "reason": "A newly discovered causal relationship starts as candidate, not established."})
        stepped = next_edge_status(
            existing,
            requested,
            independent_support_count=int(proposal.get("independent_support_count") or len(proposal.get("evidence_ids") or [])),
            independent_counter_count=int(proposal.get("independent_counter_count") or 0),
            source_kind=source,
            is_new=is_new,
        )
        if requested in {"supported", "established"} and stepped["status"] not in {"supported", "established"}:
            hits.append({"rule": "causal_slower_than_claim", "reason": "Causal Graph cannot jump to established from a single event."})
        elif source in {"news", "event", "signal", "price"} and requested in {"supported", "established"} and is_new:
            hits.append({"rule": "causal_slower_than_claim", "reason": "Causal Graph cannot jump to established from a single event."})

    supplied_edges = coerce_causal_edges(proposal.get("causal_edges") or payload.get("causal_edges") or [])
    raw_supplied = proposal.get("causal_edges") or payload.get("causal_edges") or []
    impact_targets = {"claim", "core_claim", "driver", "value_driver"}
    if target in impact_targets | {"financial_impact", "scenario"}:
        if raw_supplied and not supplied_edges:
            hits.append({"rule": "unsupported_causal_cannot_transmit", "reason": "rejected_malformed_causal_edge"})
        if supplied_edges:
            stopped = transmission_stop_reason(supplied_edges)
            if stopped:
                hits.append({"rule": "unsupported_causal_cannot_transmit", "reason": stopped})
        elif target in impact_targets and context.get("causal_edges") and context.get("event_nodes"):
            target_id = str(proposal.get("object_id") or payload.get("object_id") or "")
            if target_id:
                walked = shortest_path(
                    coerce_causal_edges(context.get("causal_edges") or []),
                    start_ids={str(item) for item in (context.get("event_nodes") or []) if str(item)},
                    goal_ids={target_id},
                )
                if walked.get("stopped"):
                    hits.append({"rule": "unsupported_causal_cannot_transmit", "reason": walked.get("reason") or "transmission_stop"})
                elif target in {"claim", "core_claim"} and not walked.get("found"):
                    hits.append({"rule": "unsupported_event_claim_jump", "reason": "Event cannot jump to this object without a transmittable causal path."})

    if target == "financial_impact" and (
        payload.get("base_case_change") is True or str(payload.get("scope") or "") == "base"
    ):
        hits.append({"rule": "financial_transmission_cannot_modify_base", "reason": "Driver → financial metric cannot directly rewrite the Base Case."})
    if target == "scenario" and (
        payload.get("base_case_change") is True or str(payload.get("scope") or "") == "base"
    ) and (payload.get("financial_metric") or payload.get("from_driver") or payload.get("driver_id")):
        hits.append({"rule": "financial_transmission_cannot_modify_base", "reason": "Driver → financial metric cannot directly rewrite the Base Case."})

    if source == "price" and target in {"claim", "core_claim", "driver", "value_driver"}:
        if not proposal.get("fundamental_evidence_ids"):
            hits.append({"rule": "unexplained_price_is_not_mispricing", "reason": "Price without fundamental evidence cannot rewrite investment reasoning."})

    investment_target = target in INVESTMENT_DOWNSTREAM
    claim_linked_impact = target == "financial_impact" and bool(payload.get("claim_id") or (payload.get("object_type") in {"claim", "core_claim"} and payload.get("object_id")))
    new_scenario = target == "scenario" and str(payload.get("scenario_type") or "") in {"bull", "base", "bear"}
    if source in {"event", "news"} and (
        target in {"valuation_state", "thesis", "thesis_snapshot"}
        or claim_linked_impact
        or new_scenario
    ):
        hits.append({"rule": "event_cannot_modify_investment_downstream", "reason": "Event cannot directly modify Financial Impact, Scenario, ValuationState, or Thesis."})
    if source == "price" and (investment_target or claim_linked_impact):
        hits.append({"rule": "price_cannot_modify_investment_downstream", "reason": "Price cannot directly modify Financial Impact, Scenario, ValuationState, or Thesis."})

    evidence_ids = [str(item) for item in (proposal.get("evidence_ids") or payload.get("evidence_ids") or []) if str(item).strip()]
    if target in conclusion_targets and price_as_evidence_forbidden(
        evidence_ids,
        price_observation_ids=[str(item) for item in (proposal.get("price_observation_ids") or payload.get("price_observation_ids") or []) if str(item).strip()],
    ):
        hits.append(
            {
                "rule": "price_cannot_modify_fundamental_state"
                if target in {"state", "company_state", "industry_state", "macro_state"}
                else "price_cannot_modify_fundamental_claim",
                "reason": "A price observation cannot be used as evidence for a later fundamental fact.",
            }
        )
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
