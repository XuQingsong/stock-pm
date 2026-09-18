"""Independent Critic: separate GLM-5.3 pass without primary chain-of-thought."""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .limits import limit_words
from .types import CRITIC_ISSUE_TYPES, CRITIC_SEVERITY


def critic_context(
    *,
    states: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    events: list[dict[str, Any]],
    transmissions: list[dict[str, Any]],
    financial_impacts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Facts, evidence, claims, and conclusions only. No primary reasoning chain."""
    return {
        "states": [
            {
                "state_id": row.get("state_id"),
                "state_type": row.get("state_type"),
                "name": row.get("name"),
                "statement": row.get("statement"),
                "direction": row.get("direction"),
                "evidence_ids": row.get("evidence_ids") or [],
            }
            for row in states
        ],
        "drivers": [
            {
                "driver_id": row.get("driver_id"),
                "canonical_key": row.get("canonical_key"),
                "name": row.get("name"),
                "category": row.get("category"),
                "current_state": row.get("current_state"),
                "evidence_ids": row.get("evidence_ids") or [],
                "missing_evidence": row.get("missing_evidence") or [],
            }
            for row in drivers
        ],
        "claims": [
            {
                "claim_id": row.get("claim_id"),
                "title": row.get("title"),
                "statement": row.get("statement"),
                "final_status": row.get("final_status") or row.get("status"),
                "confidence": row.get("confidence"),
                "related_driver_ids": row.get("related_driver_ids") or [],
                "supporting_evidence_ids": row.get("supporting_evidence_ids") or [],
                "opposing_evidence_ids": row.get("opposing_evidence_ids") or [],
            }
            for row in claims
        ],
        "events": [
            {
                "event_id": row.get("event_id"),
                "title": row.get("title"),
                "materiality": row.get("materiality"),
                "evidence_ids": row.get("evidence_ids") or [],
            }
            for row in events
        ],
        "transmissions": [
            {
                "event_id": row.get("event_id"),
                "affected_drivers": row.get("affected_drivers") or [],
                "affected_claims": row.get("affected_claims") or [],
                "direction": row.get("direction"),
                "scenario_only": row.get("scenario_only"),
                "base_case_change": row.get("base_case_change"),
                "truncated": row.get("truncated"),
                "reason": row.get("reason"),
            }
            for row in transmissions
        ],
        "financial_impacts": [
            {
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "metric": row.get("metric"),
                "direction": row.get("direction"),
                "direction_only": row.get("direction_only"),
                "evidence_ids": row.get("evidence_ids") or [],
            }
            for row in financial_impacts
        ],
        "evidence": evidence,
        "rules": [
            "You do not see primary chain-of-thought.",
            "Do not rubber-stamp. Look for leaps, missed drivers, and Base overreaction.",
        ],
    }


def incremental_critic_context(
    base: dict[str, Any],
    *,
    affected_ids: set[str] | None = None,
    expand: bool = False,
) -> dict[str, Any]:
    """Default Critic looks only at touched objects. Expand for high-risk or wide rewrites."""
    if expand or not affected_ids:
        return dict(base)
    ids = {str(item) for item in affected_ids if str(item).strip()}

    def _keep(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
        return any(str(row.get(key) or "") in ids for key in keys) or any(
            str(item) in ids for item in (row.get("evidence_ids") or [])
        )

    scoped = dict(base)
    scoped["states"] = [row for row in base.get("states") or [] if _keep(row, ("state_id", "name"))]
    scoped["drivers"] = [row for row in base.get("drivers") or [] if _keep(row, ("driver_id", "canonical_key"))]
    scoped["claims"] = [row for row in base.get("claims") or [] if _keep(row, ("claim_id",))]
    scoped["events"] = [row for row in base.get("events") or [] if _keep(row, ("event_id",))]
    scoped["transmissions"] = [
        row
        for row in base.get("transmissions") or []
        if _keep(row, ("event_id",))
        or any(str(item) in ids for item in (row.get("affected_claims") or []) + (row.get("affected_drivers") or []))
    ]
    scoped["financial_impacts"] = [row for row in base.get("financial_impacts") or [] if _keep(row, ("object_id",))]
    scoped["evidence"] = [
        row
        for row in base.get("evidence") or []
        if str(row.get("id") or row.get("evidence_id") or "") in ids
    ]
    scoped["scope"] = "incremental"
    return scoped


def normalize_issue(raw: dict[str, Any]) -> dict[str, Any] | None:
    issue_type = str(raw.get("issue_type") or "")
    if issue_type not in CRITIC_ISSUE_TYPES:
        return None
    severity = str(raw.get("severity") or "medium")
    if severity not in CRITIC_SEVERITY:
        severity = "medium"
    return {
        "issue_id": raw.get("issue_id") or new_id("bcri"),
        "issue_type": issue_type,
        "severity": severity,
        "affected_object": compact_text(raw.get("affected_object") or "", 80),
        "reasoning": limit_words(compact_text(raw.get("reasoning") or "", 400), 100),
        "required_fix": limit_words(compact_text(raw.get("required_fix") or "", 240), 40),
        "resolved": False,
    }


def reconcile_critic(
    issues: list[dict[str, Any]],
    *,
    transmissions: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = [item for item in (normalize_issue(row) for row in issues or []) if item]
    fixed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    updated = list(transmissions or [])
    for issue in normalized:
        if issue["issue_type"] == "wrong_base_case_update":
            for row in updated:
                row["scenario_only"] = True
                row["base_case_change"] = False
                row["base_block_reason"] = list(row.get("base_block_reason") or []) + ["critic:wrong_base_case_update"]
            issue["resolved"] = True
            fixed.append(issue)
            continue
        if issue["issue_type"] == "unsupported_leap" and issue["severity"] == "high":
            for row in updated:
                if row.get("truncated") or row.get("affected_claims"):
                    row["affected_claims"] = []
                    row["truncated"] = True
                    row["reason"] = row.get("reason") or "critic_unsupported_leap"
            issue["resolved"] = issue["severity"] != "high"
            if issue["resolved"]:
                fixed.append(issue)
            else:
                unresolved.append(issue)
            continue
        if issue["severity"] == "high":
            unresolved.append(issue)
        else:
            issue["resolved"] = True
            fixed.append(issue)
    high_unresolved = [row for row in unresolved if row.get("severity") == "high"]
    return {
        "issues": normalized,
        "fixed": fixed,
        "unresolved": unresolved,
        "transmissions": updated,
        "inconsistent": bool(high_unresolved),
        "status": "inconsistent" if high_unresolved else "ok",
    }
