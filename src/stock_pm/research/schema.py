"""Validate AgentOutput before persistence. Drop ungrounded or conclusion-like items."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import SchemaError
from .extract import NEWS_SOURCE_TYPES, has_conclusion_language, has_priced_in_language
from .types import (
    AGENT_FUNDAMENTAL,
    AGENT_INDUSTRY,
    AGENT_QUANT,
    AGENT_RISK,
    AGENT_SEARCH,
    PROPOSED_ASSUMPTION_STATUSES,
    PROPOSED_STATUS_ALIASES,
    AgentOutput,
    follow_up_from_payload,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clamp_confidence(value: Any) -> float | None:
    number = value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def _clean_evidence(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    fact = str(item.get("fact") or "").strip()
    source = str(item.get("source") or "").strip()
    source_time = item.get("source_time")
    evidence_type = str(item.get("evidence_type") or "fundamental").strip() or "fundamental"
    source_type = str(item.get("source_type") or "").strip()
    excerpt = str(item.get("excerpt") or "").strip()
    if not fact or not source or not source_time:
        return None
    if has_conclusion_language(fact):
        return None
    if evidence_type in NEWS_SOURCE_TYPES or source_type in NEWS_SOURCE_TYPES:
        return None
    if not excerpt:
        excerpt = fact
    payload = dict(item)
    payload["fact"] = fact
    payload["source"] = source
    payload["excerpt"] = excerpt
    payload["source_type"] = source_type or (
        "structured_provider" if evidence_type in {"fundamental", "price"} else evidence_type
    )
    payload["evidence_type"] = evidence_type
    payload.setdefault("retrieved_at", _now())
    payload.setdefault("direction", "neutral")
    if payload.get("confidence") is None:
        payload["confidence"] = 0.7 if payload["source_type"] != "structured_provider" else 0.55
    return payload


def _clean_assumption(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    statement = str(item.get("statement") or "").strip()
    if not statement or has_conclusion_language(statement):
        return None
    payload = dict(item)
    payload["statement"] = statement
    payload["status"] = "unverified"
    if payload.get("thesis_role") == "core":
        payload["thesis_role"] = "supporting"
    payload.setdefault("category", "other")
    payload.setdefault("importance", "medium")
    payload.setdefault("source_type", "template_seed")
    return payload


def _clean_proposal(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw_status = str(item.get("proposed_status") or item.get("status") or "").strip().lower()
    proposed = PROPOSED_STATUS_ALIASES.get(raw_status)
    if proposed not in PROPOSED_ASSUMPTION_STATUSES:
        return None
    reason = str(item.get("reason") or "").strip()
    if not reason or has_conclusion_language(reason) or has_priced_in_language(reason):
        return None
    assumption_id = str(item.get("assumption_id") or "").strip()
    statement = str(item.get("statement") or "").strip()
    if not assumption_id and not statement:
        return None
    gaps = item.get("unresolved_gaps") or []
    if not isinstance(gaps, list):
        gaps = [gaps]
    payload = {
        "assumption_id": assumption_id,
        "statement": statement,
        "proposed_status": proposed,
        "reason": reason,
        "confidence": _clamp_confidence(item.get("confidence")),
        "unresolved_gaps": [str(gap).strip() for gap in gaps if str(gap).strip()],
    }
    return payload


def output_from_payload(payload: dict[str, Any], *, agent_name: str = "") -> AgentOutput:
    if not isinstance(payload, dict):
        raise SchemaError("agent output must be a JSON object")
    follow_ups = []
    for item in _as_list(payload.get("follow_up_tasks")):
        try:
            spec = follow_up_from_payload(item)
        except Exception as exc:
            raise SchemaError(f"invalid follow-up: {exc}") from exc
        if spec.title:
            follow_ups.append(spec)
    findings = []
    drop_conclusions = agent_name in {
        AGENT_SEARCH,
        AGENT_FUNDAMENTAL,
        AGENT_INDUSTRY,
        AGENT_QUANT,
        AGENT_RISK,
        "",
    }
    for item in _as_list(payload.get("findings")):
        text = str(item).strip()
        if not text:
            continue
        if has_priced_in_language(text):
            continue
        if drop_conclusions and has_conclusion_language(text):
            continue
        findings.append(text)
    evidence = [row for row in (_clean_evidence(item) for item in _as_list(payload.get("new_evidence"))) if row]
    assumptions = [row for row in (_clean_assumption(item) for item in _as_list(payload.get("new_assumptions"))) if row]
    if agent_name == AGENT_SEARCH:
        assumptions = []
    proposals = [row for row in (_clean_proposal(item) for item in _as_list(payload.get("proposed_assumption_changes"))) if row]
    return AgentOutput(
        findings=findings,
        new_evidence=evidence,
        new_assumptions=assumptions,
        supported_assumption_ids=[str(item) for item in _as_list(payload.get("supported_assumption_ids")) if item],
        challenged_assumption_ids=[str(item) for item in _as_list(payload.get("challenged_assumption_ids")) if item],
        assumption_links=[dict(item) for item in _as_list(payload.get("assumption_links")) if isinstance(item, dict)],
        proposed_assumption_changes=proposals,
        follow_up_tasks=follow_ups,
        missing_data=[str(item).strip() for item in _as_list(payload.get("missing_data")) if str(item).strip()],
        confidence=_clamp_confidence(payload.get("confidence")),
        agent_name=str(payload.get("agent_name") or agent_name),
        model=payload.get("model"),
        prompt_version=payload.get("prompt_version"),
    )


def validate_agent_output(output: AgentOutput | dict[str, Any], *, agent_name: str = "") -> AgentOutput:
    if isinstance(output, AgentOutput):
        payload = {
            "findings": output.findings,
            "new_evidence": output.new_evidence,
            "new_assumptions": output.new_assumptions,
            "supported_assumption_ids": output.supported_assumption_ids,
            "challenged_assumption_ids": output.challenged_assumption_ids,
            "assumption_links": output.assumption_links,
            "proposed_assumption_changes": output.proposed_assumption_changes,
            "follow_up_tasks": output.follow_up_tasks,
            "missing_data": output.missing_data,
            "confidence": output.confidence,
            "agent_name": output.agent_name or agent_name,
            "model": output.model,
            "prompt_version": output.prompt_version,
        }
        name = output.agent_name or agent_name
    else:
        payload = dict(output)
        name = str(payload.get("agent_name") or agent_name)
    cleaned = output_from_payload(payload, agent_name=name)
    if name in {AGENT_FUNDAMENTAL, AGENT_QUANT, AGENT_INDUSTRY, AGENT_RISK} and (
        has_conclusion_language(" ".join(cleaned.findings)) or has_priced_in_language(" ".join(cleaned.findings))
    ):
        cleaned.findings = [
            item
            for item in cleaned.findings
            if not has_conclusion_language(item) and not has_priced_in_language(item)
        ]
    return cleaned
