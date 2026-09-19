"""Deterministic market-layer interpretation. LLM may also propose; constitution still gates writes."""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text

from .expectation import expectation_from_event
from .hypothesis import hypotheses_from_event, is_unresolved_price


def interpret_market_layer(
    event: dict[str, Any] | None,
    *,
    ticker: str,
    existing_expectations: list[dict[str, Any]] | None = None,
    existing_hypotheses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = event or {}
    symbol = str(ticker).upper()
    expectation = expectation_from_event(item, ticker=symbol)
    if expectation and existing_expectations:
        match = next((row for row in existing_expectations if str(row.get("name") or "") == expectation["name"]), None)
        if match:
            expectation["expectation_id"] = match.get("expectation_id")
    hyp = hypotheses_from_event(item, ticker=symbol, existing=existing_hypotheses)
    for row in list(hyp.get("created") or []) + list(hyp.get("updated") or []):
        if expectation and not row.get("related_expectation_id"):
            row["related_expectation_id"] = expectation.get("expectation_id")
        path = [str(item.get("event_key") or item.get("subject") or "")]
        path = [node for node in path if node]
        if path and not row.get("related_causal_path"):
            row["related_causal_path"] = path
    unresolved = is_unresolved_price(item, expectation=expectation, peer=hyp.get("peer_pattern"))
    proposals: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    if expectation:
        proposals.append(
            {
                "object_type": "expectation",
                "object_id": expectation.get("expectation_id"),
                "source_kind": expectation.get("source_kind") or "news",
                "fact_reliability": item.get("fact_reliability"),
                "to": expectation,
                "reason": expectation.get("reason"),
            }
        )
    for row in hyp.get("created") or []:
        proposals.append(
            {
                "object_type": "market_driver_hypothesis",
                "object_id": row.get("hypothesis_id"),
                "source_kind": row.get("source_kind") or "news",
                "fact_reliability": item.get("fact_reliability"),
                "to": row,
                "reason": "Candidate market driver hypothesis; not a fact.",
            }
        )
    for row in hyp.get("updated") or []:
        proposals.append(
            {
                "object_type": "market_driver_hypothesis",
                "object_id": row.get("hypothesis_id"),
                "source_kind": row.get("source_kind") or "news",
                "fact_reliability": item.get("fact_reliability"),
                "to": row,
                "from": next((item for item in (existing_hypotheses or []) if item.get("canonical_key") == row.get("canonical_key")), {}),
                "reason": "Update existing market driver hypothesis.",
            }
        )
    if unresolved:
        question = "What is the market pricing that the current Brain does not explain?"
        questions.append({"question": question, "reason": "Large price move is unresolved.", "related_objects": [symbol]})
        proposals.append(
            {
                "object_type": "research_question",
                "source_kind": item.get("kind") or "price",
                "to": {"question": question},
                "reason": "Price move is large, expectation did not clearly change, and peers do not support a driver.",
            }
        )
        proposals.append(
            {
                "object_type": "market_driver_hypothesis",
                "source_kind": "price",
                "to": {
                    "canonical_key": "unresolved",
                    "kind": "other",
                    "hypothesis": "Market driver is unresolved",
                    "status": "unresolved",
                    "confidence": "low",
                    "supporting_observations": [compact_text(item.get("title") or "price move", 120)],
                },
                "reason": "Do not force a winner.",
            }
        )
    created = len(hyp.get("created") or [])
    updated = len(hyp.get("updated") or [])
    if unresolved:
        created += 1
    competing = created + updated + (1 if expectation else 0)
    return {
        "proposals": proposals,
        "questions": questions,
        "expectation": expectation,
        "hypotheses_created": hyp.get("created") or [],
        "hypotheses_updated": hyp.get("updated") or [],
        "unresolved": unresolved,
        "stats": {
            "expectation_changes": 1 if expectation else 0,
            "hypotheses_created": created,
            "hypotheses_updated": updated,
            "competing_hypotheses": max(created + updated, 0),
            "hypothesis_strengthened": int(hyp.get("hypothesis_strengthened") or updated),
            "hypothesis_weakened": int(hyp.get("hypothesis_weakened") or 0),
            "hypothesis_closed": int(hyp.get("hypothesis_closed") or 0),
            "duplicates_prevented": int(hyp.get("duplicates_prevented") or 0),
            "unresolved_events": 1 if unresolved else 0,
            "research_questions": len(questions),
            "peer_observations_used": int(hyp.get("peer_observations_used") or 0),
        },
        "competing": competing,
    }


def merge_market_proposals(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    out = list(existing or [])
    seen: set[str] = set()
    for row in out:
        payload = row.get("to") or row.get("to_payload") or {}
        token = str(payload.get("canonical_key") or payload.get("name") or payload.get("signature") or row.get("object_type") or "")
        if token:
            seen.add(f"{row.get('object_type')}:{token}")
    extra = 0
    skipped = 0
    for row in incoming or []:
        payload = row.get("to") or row.get("to_payload") or {}
        token = str(payload.get("canonical_key") or payload.get("name") or payload.get("signature") or "")
        key = f"{row.get('object_type')}:{token}"
        if token and key in seen:
            skipped += 1
            continue
        if token:
            seen.add(key)
        out.append(row)
        extra += 1
    return out, skipped
