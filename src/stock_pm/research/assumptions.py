"""Assumption Engine: aggregate evidence and propose status. Never write status."""

from __future__ import annotations

from typing import Any

from .extract import OFFICIAL_SOURCE_TYPES
from .types import (
    AGENT_ASSUMPTION_ENGINE,
    IMPORTANCE_LEVELS,
    PROPOSED_ASSUMPTION_STATUSES,
    THESIS_ROLES,
    to_plain,
)


STRENGTH_WEIGHT = {"strong": 1.0, "moderate": 0.65, "weak": 0.3}


def _quality(evidence: dict[str, Any] | None) -> float:
    row = evidence or {}
    source_type = str(row.get("source_type") or "")
    evidence_type = str(row.get("evidence_type") or "")
    if source_type in OFFICIAL_SOURCE_TYPES or evidence_type in {"filing", "guidance", "transcript"}:
        return 1.0
    if evidence_type in {"industry", "competitive"}:
        return 0.8
    if evidence_type == "quant":
        return 0.7
    if evidence_type == "fundamental":
        return 0.7
    return 0.4


def link_score(link: dict[str, Any], evidence: dict[str, Any] | None) -> float:
    weight = STRENGTH_WEIGHT.get(str(link.get("strength") or "moderate"), 0.65)
    return weight * _quality(evidence)


def propose_status(support_score: float, oppose_score: float) -> str:
    """Map scores to suggestion verbs. Does not map onto assumption.status."""
    if oppose_score >= 2.0 and oppose_score >= 2 * max(support_score, 0.35):
        return "broken"
    if oppose_score > support_score + 0.25:
        return "weaken"
    if support_score >= 1.2 and support_score >= 2 * max(oppose_score, 0.2):
        return "strengthen"
    return "unchanged"


def _confidence(support_score: float, oppose_score: float, contextual_score: float) -> float:
    total = support_score + oppose_score + 0.25 * contextual_score
    if total <= 0:
        return 0.2
    spread = abs(support_score - oppose_score)
    value = 0.3 + min(0.45, 0.12 * total) + min(0.15, 0.08 * spread)
    if oppose_score > 0 and support_score > 0:
        value -= 0.05
    return round(min(0.85, max(0.15, value)), 3)


def _gaps_for(assumption: dict[str, Any], buckets: dict[str, list[dict[str, Any]]]) -> list[str]:
    gaps: list[str] = []
    category = str(assumption.get("category") or "")
    next_check = str(assumption.get("next_verification") or "").strip()
    if not buckets["support"]:
        gaps.append("no supporting evidence linked yet")
    if not buckets["oppose"]:
        gaps.append("no opposing evidence; assumption is untested by a skeptic pass")
    if next_check:
        gaps.append(next_check)
    if category in {"demand", "guidance_delivery"} and not any(
        "customer" in str(item.get("fact") or "").lower()
        or str(item.get("evidence_type") or "") in {"industry", "competitive"}
        for item in buckets["support"] + buckets["contextual"]
    ):
        gaps.append("demand claim still lacks customer-side confirmation")
    if category in {"execution", "supply"} and not any(
        token in str(item.get("fact") or "").lower()
        for item in buckets["support"] + buckets["contextual"]
        for token in ("capacity", "supply", "contract", "capex", "production")
    ):
        gaps.append("delivery claim still lacks supply, contract, or capex support")
    if str(assumption.get("status") or "unverified") == "unverified":
        gaps.append("status remains unverified until PM/Judge reviews the proposal")
    seen: set[str] = set()
    unique: list[str] = []
    for item in gaps:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:8]


def summarize_assumption(
    assumption: dict[str, Any],
    *,
    links: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {"support": [], "oppose": [], "contextual": []}
    scores = {"support": 0.0, "oppose": 0.0, "contextual": 0.0}
    for link in links:
        direction = str(link.get("direction") or "")
        if direction not in buckets:
            continue
        evidence = evidence_by_id.get(str(link.get("evidence_id") or ""))
        score = link_score(link, evidence)
        scores[direction] += score
        fact = dict(evidence or {})
        fact["link_strength"] = link.get("strength")
        fact["link_reason"] = link.get("reason")
        buckets[direction].append(fact)
    proposed = propose_status(scores["support"], scores["oppose"])
    importance = str(assumption.get("importance") or "medium")
    if importance not in IMPORTANCE_LEVELS:
        importance = "medium"
    thesis_role = str(assumption.get("thesis_role") or "supporting")
    if thesis_role not in THESIS_ROLES:
        thesis_role = "supporting"
    reason_parts = [
        f"support_score={round(scores['support'], 2)}",
        f"oppose_score={round(scores['oppose'], 2)}",
        f"contextual={len(buckets['contextual'])}",
    ]
    if proposed == "strengthen":
        reason_parts.append("supporting evidence outweighs opposing evidence")
    elif proposed == "weaken":
        reason_parts.append("opposing evidence outweighs supporting evidence")
    elif proposed == "broken":
        reason_parts.append("opposing evidence is strong enough to challenge the claim")
    else:
        reason_parts.append("evidence mix does not yet justify a status change")
    return {
        "assumption_id": assumption.get("id"),
        "statement": assumption.get("statement"),
        "status": assumption.get("status") or "unverified",
        "category": assumption.get("category"),
        "importance": importance,
        "thesis_role": thesis_role,
        "confidence": _confidence(scores["support"], scores["oppose"], scores["contextual"]),
        "supporting_evidence": buckets["support"],
        "opposing_evidence": buckets["oppose"],
        "contextual_evidence": buckets["contextual"],
        "supporting_count": len(buckets["support"]),
        "opposing_count": len(buckets["oppose"]),
        "contextual_count": len(buckets["contextual"]),
        "support_score": round(scores["support"], 3),
        "oppose_score": round(scores["oppose"], 3),
        "proposed_status": proposed,
        "reason": "; ".join(reason_parts),
        "unresolved_gaps": _gaps_for(assumption, buckets),
    }


def engine_views_for_ticker(service: Any, ticker: str) -> list[dict[str, Any]]:
    evidence_by_id = {row["id"]: row for row in service.store.list_evidence(ticker)}
    views = []
    for assumption in service.store.list_assumptions(ticker):
        links = service.store.list_links(assumption_id=assumption["id"])
        views.append(summarize_assumption(assumption, links=links, evidence_by_id=evidence_by_id))
    return views


def record_engine_proposals(
    service: Any,
    ticker: str,
    *,
    workflow_run_id: str | None = None,
    produced_by: str = AGENT_ASSUMPTION_ENGINE,
) -> list[dict[str, Any]]:
    """Persist suggested states. Leaves research_assumptions.status untouched."""
    views = engine_views_for_ticker(service, ticker)
    recorded = []
    for view in views:
        proposal = service.record_assumption_proposal(
            ticker,
            {
                "assumption_id": view["assumption_id"],
                "current_status": view["status"],
                "proposed_status": view["proposed_status"],
                "reason": view["reason"],
                "confidence": view["confidence"],
                "supporting_count": view["supporting_count"],
                "opposing_count": view["opposing_count"],
                "contextual_count": view["contextual_count"],
                "unresolved_gaps": view["unresolved_gaps"],
                "produced_by": produced_by,
                "workflow_run_id": workflow_run_id,
            },
        )
        recorded.append({**view, "proposal_id": proposal.get("id"), "produced_by": produced_by})
    return recorded


def snapshot_engine(service: Any, ticker: str) -> dict[str, Any]:
    views = engine_views_for_ticker(service, ticker)
    proposals = []
    lister = getattr(service.store, "list_assumption_proposals", None)
    if callable(lister):
        proposals = lister(ticker)
    return {
        "assumptions": [to_plain(row) for row in views],
        "proposals": [to_plain(row) for row in proposals],
        "proposed_status_values": list(PROPOSED_ASSUMPTION_STATUSES),
    }
