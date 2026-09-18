"""PM synthesis may read only validated Brain objects."""

from __future__ import annotations

from typing import Any

from .history import why_thesis_changed
from .limits import limit_words


def pm_context(
    *,
    ticker: str,
    states: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    financial_impacts: list[dict[str, Any]],
    transmissions: list[dict[str, Any]],
    history: list[dict[str, Any]],
    rejected_ids: set[str] | None = None,
) -> dict[str, Any]:
    blocked = set(rejected_ids or [])
    bound_ids: set[str] = set()
    for row in claims:
        for eid in list(row.get("supporting_evidence_ids") or []) + list(row.get("opposing_evidence_ids") or []):
            if eid and eid not in blocked:
                bound_ids.add(str(eid))
        for link in row.get("evidence_links") or []:
            eid = str(link.get("evidence_id") or "")
            if eid and eid not in blocked:
                bound_ids.add(eid)
    for row in drivers:
        for eid in row.get("evidence_ids") or []:
            if eid and eid not in blocked:
                bound_ids.add(str(eid))
    evidence = []
    for eid in bound_ids:
        row = evidence_by_id.get(eid)
        if not row:
            continue
        evidence.append(
            {
                "id": row.get("id") or eid,
                "fact": row.get("fact"),
                "excerpt": row.get("excerpt") or row.get("fact"),
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "source_relationship": row.get("source_relationship"),
            }
        )
    core = []
    for row in claims:
        if not row.get("is_core") and str(row.get("lifecycle") or "") not in {"core", "challenged", "confirmed"}:
            continue
        core.append(
            {
                "claim_id": row.get("claim_id"),
                "title": row.get("title"),
                "statement": row.get("statement"),
                "final_status": row.get("final_status") or row.get("status"),
                "confidence": row.get("confidence"),
                "lifecycle": row.get("lifecycle"),
                "related_driver_ids": row.get("related_driver_ids") or [],
                "supporting_evidence_ids": [eid for eid in (row.get("supporting_evidence_ids") or []) if eid not in blocked],
                "opposing_evidence_ids": [eid for eid in (row.get("opposing_evidence_ids") or []) if eid not in blocked],
                "why_it_matters": limit_words(row.get("why_it_matters") or "", 40),
            }
        )
    return {
        "ticker": ticker,
        "states": [
            {
                "state_id": row.get("state_id"),
                "state_type": row.get("state_type"),
                "name": row.get("name"),
                "statement": row.get("statement"),
                "direction": row.get("direction"),
                "confidence": row.get("confidence"),
            }
            for row in states
            if (row.get("evidence_ids") or row.get("statement"))
        ],
        "drivers": [
            {
                "driver_id": row.get("driver_id"),
                "canonical_key": row.get("canonical_key"),
                "name": row.get("name"),
                "category": row.get("category"),
                "current_state": row.get("current_state"),
                "importance": row.get("importance"),
                "uncertainty": row.get("uncertainty"),
                "why_it_matters": limit_words(row.get("why_it_matters") or "", 40),
                "evidence_ids": [eid for eid in (row.get("evidence_ids") or []) if eid not in blocked],
            }
            for row in drivers
            if str(row.get("status") or "active") not in {"closed", "retired"}
        ],
        "core_claims": core,
        "evidence": evidence,
        "financial_impacts": [
            {
                "object_type": row.get("object_type"),
                "metric": row.get("metric"),
                "direction": row.get("direction"),
                "direction_only": row.get("direction_only"),
                "time_horizon": row.get("time_horizon"),
                "mechanism": row.get("mechanism"),
            }
            for row in financial_impacts
        ],
        "scenario": [
            {
                "event_id": row.get("event_id"),
                "scenario_only": row.get("scenario_only"),
                "base_case_change": row.get("base_case_change"),
                "direction": row.get("direction"),
                "affected_claims": row.get("affected_claims") or [],
            }
            for row in transmissions
        ],
        "history": why_thesis_changed(history)[-12:],
        "forbidden": ["rejected_facts", "unsupported_numbers", "raw_llm_speculation"],
    }


def assert_pm_cannot_see_rejected(payload: dict[str, Any], rejected_ids: set[str]) -> bool:
    blob = str(payload)
    return not any(eid and eid in blob for eid in rejected_ids)
