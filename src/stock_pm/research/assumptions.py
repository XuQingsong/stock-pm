"""Assumption Engine: weight evidence by quality, relevance, strength, and independence.

Never write research_assumptions.status. PM/Judge remains the only status actor.
"""

from __future__ import annotations

from typing import Any

from .relevance import (
    cluster_family_weights,
    independence_key_for,
    judge_link,
    link_weight,
    source_quality_for,
)
from .types import (
    AGENT_ASSUMPTION_ENGINE,
    IMPORTANCE_LEVELS,
    PROPOSED_ASSUMPTION_STATUSES,
    THESIS_ROLES,
    to_plain,
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(min(high, max(low, value)), 3)


def propose_status(
    support_score: float,
    oppose_score: float,
    *,
    direct_support_families: int | None = None,
    hard_oppose_score: float | None = None,
    material_gaps: int = 0,
) -> str:
    """Map calibrated scores to suggestion verbs. Does not write assumption.status."""
    oppose_for_break = hard_oppose_score if hard_oppose_score is not None else oppose_score
    if oppose_for_break >= 1.6 and oppose_for_break >= 2 * max(support_score, 0.35):
        return "broken"
    if oppose_for_break > support_score + 0.25 and oppose_for_break >= 0.55:
        return "weaken"
    if direct_support_families is None:
        if support_score >= 1.2 and support_score >= 2 * max(oppose_score, 0.2):
            return "strengthen"
        return "unchanged"
    if material_gaps >= 2:
        return "unchanged"
    if (
        direct_support_families >= 1
        and support_score >= 0.7
        and oppose_for_break < 0.4
        and material_gaps <= 1
    ):
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
    return _clamp(value, 0.15, 0.85)


def _material_gap(text: str) -> bool:
    hay = text.lower()
    return any(
        token in hay
        for token in (
            "customer",
            "capex",
            "power",
            "site",
            "independent",
            "named",
            "confirmation",
            "fulfill",
        )
    )


def _gaps_for(assumption: dict[str, Any], buckets: dict[str, list[dict[str, Any]]]) -> list[str]:
    gaps: list[str] = []
    category = str(assumption.get("category") or "")
    next_check = str(assumption.get("next_verification") or "").strip()
    if not buckets["support"]:
        gaps.append("no supporting evidence linked yet")
    if not buckets["oppose"]:
        gaps.append("未发现足够反证")
    if next_check:
        gaps.append(next_check)
    support_and_context = buckets["support"] + buckets["contextual"]
    hay = " ".join(str(item.get("fact") or "") for item in support_and_context).lower()
    if category in {"demand", "guidance_delivery"} and "customer" not in hay:
        gaps.append("demand claim still lacks independent customer-side confirmation")
    if category in {"execution", "supply"} and not any(
        token in hay for token in ("capacity", "supply", "contract", "capex", "production")
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


def _resolved_judgment(
    link: dict[str, Any],
    evidence: dict[str, Any] | None,
    assumption: dict[str, Any],
) -> dict[str, str]:
    judged = judge_link(evidence or {}, assumption) or {}
    direction = str(link.get("direction") or judged.get("direction") or "contextual")
    strength = str(link.get("strength") or judged.get("strength") or "moderate")
    relevance = str(link.get("relevance") or judged.get("relevance") or "indirect")
    reason = str(link.get("reason") or judged.get("reason") or "")
    return {
        "direction": direction,
        "strength": strength,
        "relevance": relevance,
        "reason": reason,
    }


def _delta_for(proposed: str, support_score: float, hard_oppose: float, material_gaps: int) -> float:
    if proposed == "strengthen":
        return min(0.18, 0.08 + 0.05 * support_score)
    if proposed == "weaken":
        return -min(0.18, 0.08 + 0.05 * hard_oppose)
    if proposed == "broken":
        return -min(0.3, 0.12 + 0.08 * hard_oppose)
    net = support_score - hard_oppose
    if net > 0.25 and material_gaps:
        return min(0.06, 0.03 * net)
    if net < -0.2:
        return max(-0.06, 0.03 * net)
    return 0.0


def summarize_assumption(
    assumption: dict[str, Any],
    *,
    links: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {"support": [], "oppose": [], "contextual": []}
    scored: dict[str, list[tuple[dict[str, Any], dict[str, Any], float]]] = {
        "support": [],
        "oppose": [],
        "contextual": [],
    }
    for link in links:
        evidence = evidence_by_id.get(str(link.get("evidence_id") or "")) or {}
        judgment = _resolved_judgment(link, evidence, assumption)
        direction = judgment["direction"]
        if direction not in buckets:
            continue
        weight = link_weight(evidence, judgment)
        fact = dict(evidence)
        fact["link_strength"] = judgment["strength"]
        fact["link_relevance"] = judgment["relevance"]
        fact["link_reason"] = judgment["reason"]
        fact["independence_key"] = independence_key_for(evidence)
        fact["source_quality"] = source_quality_for(evidence)
        fact["link_weight"] = round(weight, 4)
        buckets[direction].append(fact)
        scored[direction].append((evidence, judgment, weight))

    families = {
        direction: cluster_family_weights(items) for direction, items in scored.items()
    }
    scores = {
        direction: round(sum(item["weight"] for item in rows), 3) for direction, rows in families.items()
    }
    hard_oppose_families = [
        item
        for item in families["oppose"]
        if item.get("relevance") == "direct" and item.get("strength") in {"strong", "moderate"}
    ]
    hard_oppose_score = round(sum(item["weight"] for item in hard_oppose_families), 3)
    direct_support_families = [
        item
        for item in families["support"]
        if item.get("relevance") == "direct" and item.get("strength") in {"strong", "moderate"}
    ]
    gaps = _gaps_for(assumption, buckets)
    material_gaps = sum(1 for item in gaps if _material_gap(item))
    proposed = propose_status(
        scores["support"],
        scores["oppose"],
        direct_support_families=len(direct_support_families),
        hard_oppose_score=hard_oppose_score,
        material_gaps=material_gaps,
    )
    importance = str(assumption.get("importance") or "medium")
    if importance not in IMPORTANCE_LEVELS:
        importance = "medium"
    thesis_role = str(assumption.get("thesis_role") or "supporting")
    if thesis_role not in THESIS_ROLES:
        thesis_role = "supporting"

    positives = [
        f"{item['fact'][:160]} [{item.get('relevance')}/{item.get('strength')}]"
        for item in families["support"][:4]
        if item.get("fact")
    ]
    limits = list(gaps)
    clustered = [
        item
        for rows in families.values()
        for item in rows
        if int(item.get("members") or 1) > 1
    ]
    if clustered:
        limits.append(
            "same-source excerpts were clustered into "
            + str(len(clustered))
            + " independent evidence families"
        )
    current_confidence = assumption.get("confidence")
    try:
        current = float(current_confidence) if current_confidence is not None else 0.5
    except (TypeError, ValueError):
        current = 0.5
    delta = round(_delta_for(proposed, scores["support"], hard_oppose_score, material_gaps), 3)
    proposed_confidence = _clamp(current + delta)
    reason_parts = [
        f"support_score={scores['support']}",
        f"oppose_score={scores['oppose']}",
        f"hard_oppose={hard_oppose_score}",
        f"direct_support_families={len(direct_support_families)}",
        f"independent_families={sum(len(rows) for rows in families.values())}",
    ]
    if proposed == "strengthen":
        reason_parts.append("independent direct support outweighs opposition and remaining gaps")
    elif proposed == "weaken":
        reason_parts.append("hard opposing evidence outweighs support")
    elif proposed == "broken":
        reason_parts.append("hard opposing evidence is strong enough to challenge the claim")
    elif positives and material_gaps:
        reason_parts.append("support exists but unresolved gaps keep the suggestion unchanged")
    else:
        reason_parts.append("evidence mix does not yet justify a status change")
    reason = "; ".join(reason_parts)
    reasoning = {
        "positives": positives,
        "limits": limits,
        "families": [
            {
                "independence_key": item["independence_key"],
                "direction": item["direction"],
                "weight": item["weight"],
                "members": item.get("members") or 1,
                "relevance": item.get("relevance"),
                "strength": item.get("strength"),
            }
            for item in families["support"] + families["oppose"] + families["contextual"]
        ],
        "why": reason,
    }
    return {
        "assumption_id": assumption.get("id"),
        "statement": assumption.get("statement"),
        "status": assumption.get("status") or "unverified",
        "category": assumption.get("category"),
        "importance": importance,
        "thesis_role": thesis_role,
        "confidence": proposed_confidence,
        "current_confidence": round(current, 3),
        "proposed_change": proposed,
        "confidence_delta": delta,
        "reasoning": reasoning,
        "supporting_evidence": buckets["support"],
        "opposing_evidence": buckets["oppose"],
        "contextual_evidence": buckets["contextual"],
        "supporting_count": len(families["support"]),
        "opposing_count": len(families["oppose"]),
        "contextual_count": len(families["contextual"]),
        "support_score": scores["support"],
        "oppose_score": scores["oppose"],
        "proposed_status": proposed,
        "reason": reason,
        "unresolved_gaps": gaps,
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
                "current_confidence": view["current_confidence"],
                "confidence_delta": view["confidence_delta"],
                "reasoning": view["reasoning"],
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
