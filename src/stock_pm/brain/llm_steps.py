"""LLM steps A–E. Completer is required; missing/failed calls fail loudly."""

from __future__ import annotations

import re
from importlib.resources import files
from typing import Any

from stock_pm.research.llm_reason import compact_evidence, compact_text, complete_structured, dump_user

from .types import (
    CLAIM_STATUSES,
    CLAIM_TYPES,
    CONFIDENCE,
    HORIZONS,
    IMPORTANCE,
    LINK_DIRECTIONS,
    NEWS_LAYERS,
)


def load_brain_prompt(name: str) -> str:
    path = files("stock_pm").joinpath(f"brain/prompts/{name}")
    return path.read_text(encoding="utf-8").strip()


def _filter_ids(values: Any, allowed: set[str]) -> list[str]:
    out: list[str] = []
    for item in values or []:
        key = str(item or "").strip()
        if key and key in allowed and key not in out:
            out.append(key)
    return out


def call_step(
    completer: Any,
    *,
    step: str,
    prompt_file: str,
    user: dict[str, Any],
    allowed_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload, audit = complete_structured(
        completer,
        system=load_brain_prompt(prompt_file),
        user=dump_user(user),
        allowed_ids=allowed_ids,
    )
    audit = dict(audit or {})
    audit["step"] = step
    return payload, audit


def company_understanding(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="company_understanding",
        prompt_file="company_understanding.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def value_driver_universe(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="value_drivers",
        prompt_file="value_drivers.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def core_claims(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="core_claims",
        prompt_file="core_claims.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def event_transmission(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="event_transmission",
        prompt_file="event_transmission.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def independent_critic(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="independent_critic",
        prompt_file="independent_critic.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def news_interpretation(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="news_interpretation",
        prompt_file="news_interpretation.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def claim_reasoning(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="claim_reasoning",
        prompt_file="claim_reasoning.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def pm_synthesis(completer: Any, user: dict[str, Any], *, allowed_ids: set[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return call_step(
        completer,
        step="pm_synthesis",
        prompt_file="pm_synthesis.txt",
        user=user,
        allowed_ids=allowed_ids,
    )


def normalize_claim(raw: dict[str, Any], *, allowed_ids: set[str], core: bool) -> dict[str, Any] | None:
    statement = compact_text(raw.get("statement") or raw.get("title") or "", 600)
    title = compact_text(raw.get("title") or statement, 120)
    if not statement:
        return None
    support, rejected_support = _split_ids(raw.get("supporting_evidence_ids") or raw.get("evidence_ids"), allowed_ids)
    oppose, rejected_oppose = _split_ids(raw.get("opposing_evidence_ids"), allowed_ids)
    if core and not support:
        return None
    if core and not compact_text(raw.get("why_it_matters") or "", 400):
        return None
    if core and not compact_text(raw.get("uncertainty") or (raw.get("scores") or {}).get("uncertainty") or "", 40):
        return None
    if core and not compact_text(raw.get("valuation_relevance") or (raw.get("scores") or {}).get("valuation_relevance") or "", 40):
        return None
    claim_type = str(raw.get("claim_type") or "operating")
    if claim_type not in CLAIM_TYPES:
        claim_type = "operating"
    proposed = str(raw.get("proposed_status") or raw.get("status") or ("partially_supported" if support else "unverified"))
    if proposed not in CLAIM_STATUSES:
        proposed = "emerging"
    importance = str(raw.get("importance") or "medium")
    if importance not in IMPORTANCE:
        importance = "medium"
    confidence = str(raw.get("confidence") or "low")
    if confidence not in CONFIDENCE:
        confidence = "low"
    horizon = raw.get("time_horizon")
    if horizon not in HORIZONS:
        horizon = None
    questions = [compact_text(item, 160) for item in (raw.get("counter_research_questions") or []) if str(item).strip()][:4]
    return {
        "title": title,
        "statement": statement,
        "claim_type": claim_type,
        "status": proposed,
        "proposed_status": proposed,
        "importance": importance,
        "confidence": confidence,
        "time_horizon": horizon,
        "why_it_matters": compact_text(raw.get("why_it_matters") or "", 400),
        "financial_driver": compact_text(raw.get("financial_driver") or "", 80) or None,
        "claim_subject": compact_text(raw.get("claim_subject") or "", 80) or None,
        "claim_dimension": compact_text(raw.get("claim_dimension") or "", 80) or None,
        "claim_key": compact_text(raw.get("claim_key") or "", 80) or None,
        "related_driver_ids": [str(item).strip() for item in (raw.get("related_driver_ids") or []) if str(item).strip()][:8],
        "why_core": compact_text(raw.get("why_core") or "", 240),
        "why_not_core": compact_text(raw.get("why_not_core") or "", 240),
        "evidence_boundary": compact_text(raw.get("evidence_boundary") or "", 400) or None,
        "supporting_evidence_ids": support,
        "opposing_evidence_ids": oppose,
        "rejected_evidence_ids": rejected_support + rejected_oppose,
        "missing_evidence": [compact_text(item, 160) for item in (raw.get("missing_evidence") or []) if str(item).strip()][:6],
        "counter_research_questions": questions,
        "is_core": core,
        "scores": {
            "value_impact": raw.get("value_impact"),
            "uncertainty": raw.get("uncertainty"),
            "valuation_relevance": raw.get("valuation_relevance"),
            "persistence": raw.get("persistence"),
            "testability": raw.get("testability"),
        },
    }


def _split_ids(values: Any, allowed: set[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    rejected: list[str] = []
    for item in values or []:
        key = str(item or "").strip()
        if not key:
            continue
        if key in allowed:
            if key not in kept:
                kept.append(key)
        elif key not in rejected:
            rejected.append(key)
    return kept, rejected


def normalize_news_item(raw: dict[str, Any], *, allowed_ids: set[str], claim_ids: set[str]) -> dict[str, Any]:
    layer = str(raw.get("layer") or "uninterpreted")
    if layer not in NEWS_LAYERS:
        layer = "uninterpreted"
    impact = str(raw.get("impact") or "none")
    if impact not in LINK_DIRECTIONS and impact not in {"none", "support", "oppose", "contextual"}:
        impact = "none"
    evidence_id = str(raw.get("evidence_id") or "").strip()
    if evidence_id and evidence_id not in allowed_ids:
        evidence_id = ""
    claim_id = str(raw.get("affected_claim_id") or "").strip()
    if claim_id and claim_id not in claim_ids:
        claim_id = ""
    quantifiable = bool(raw.get("quantifiable"))
    financial = str(raw.get("financial_impact") or "unavailable")
    if quantifiable and financial in {"unavailable", "none", ""}:
        quantifiable = False
        financial = "unavailable"
    return {
        "news_index": raw.get("news_index"),
        "evidence_id": evidence_id or None,
        "layer": layer,
        "new_fact": compact_text(raw.get("new_fact") or "", 400),
        "source_credibility": raw.get("source_credibility") or "unknown",
        "novelty": raw.get("novelty") or "unknown",
        "affected_state": compact_text(raw.get("affected_state") or "", 80),
        "affected_claim_id": claim_id or None,
        "impact": impact,
        "changes_claim_status": bool(raw.get("changes_claim_status")),
        "new_research_question": compact_text(raw.get("new_research_question") or "", 240),
        "financial_impact": financial,
        "quantifiable": quantifiable,
        "quantifiable_reason": compact_text(raw.get("quantifiable_reason") or "", 200),
        "reason": compact_text(raw.get("reason") or "", 400),
    }


def compact_evidence_rows(rows: list[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    base = compact_evidence(rows, limit=limit)
    by_id = {str(row.get("id")): row for row in rows if row.get("id")}
    for item in base:
        raw = by_id.get(str(item.get("id") or ""))
        if not raw:
            continue
        item["source_time"] = raw.get("source_time")
        item["excerpt"] = compact_text(raw.get("excerpt") or raw.get("fact"), 240)
        item["source_relationship"] = raw.get("source_relationship")
        item["source_tier"] = raw.get("source_tier")
    return base
