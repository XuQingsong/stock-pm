"""Phase 0 runtime: LLM may propose; code decides whether Brain can change.

Does not call live models. Fixtures / mock proposals feed this gate.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .budget import change_scope
from .claim_integrity import news_is_duplicate
from .constitution import constitution_violations, is_weak_signal
from .events import make_event_fingerprint
from .hysteresis import accumulate_claim_evidence
from .knowledge import fact_reliability
from .layers import object_layer
from .shadow import normalize_shadow, should_enter_shadow
from .types import PROPOSAL_DECISIONS


def _observation_identity(item: dict[str, Any]) -> str:
    key = compact_text(item.get("event_key") or "", 80).lower()
    if key:
        return f"key:{key}"
    subject = compact_text(item.get("subject") or "", 80).lower()
    if subject:
        return f"subject:{subject}"
    title = compact_text(item.get("title") or item.get("fact") or item.get("statement") or "", 160).lower()
    for sep in (" - ", " — ", " | "):
        if sep in title:
            title = title.split(sep)[0].strip()
    return f"title:{title}"


def normalize_proposal(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    target = str(raw.get("object_type") or raw.get("target_type") or "")
    from_payload = dict(raw.get("from_payload") or raw.get("from") or {})
    to_payload = dict(raw.get("to_payload") or raw.get("to") or {})
    return {
        "proposal_id": raw.get("proposal_id") or new_id("bcpr"),
        "ticker": str(ticker).upper(),
        "object_type": target,
        "object_id": str(raw.get("object_id") or to_payload.get("object_id") or from_payload.get("object_id") or ""),
        "from_payload": from_payload,
        "to_payload": to_payload,
        "reason": compact_text(raw.get("reason") or raw.get("why") or "", 400),
        "evidence_ids": [str(item) for item in (raw.get("evidence_ids") or to_payload.get("evidence_ids") or []) if str(item).strip()],
        "source_kind": str(raw.get("source_kind") or raw.get("kind") or "news"),
        "confidence": raw.get("confidence"),
        "fact_reliability": raw.get("fact_reliability") or fact_reliability(raw),
        "title": raw.get("title"),
        "new_fact": raw.get("new_fact"),
        "duplicate": bool(raw.get("duplicate")),
        "causal_edges": list(raw.get("causal_edges") or []),
        "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), dict) else None,
        "is_core": bool(raw.get("is_core") or from_payload.get("is_core") or to_payload.get("is_core")),
        "independent_counter_count": int(raw.get("independent_counter_count") or 0),
        "fundamental_evidence_ids": list(raw.get("fundamental_evidence_ids") or []),
        "layer": object_layer(target),
        "decision": None,
        "rules": [],
        "reason_code": str(raw.get("reason_code") or ""),
        "related_objects": [str(item) for item in (raw.get("related_objects") or []) if str(item).strip()],
    }


def _research_question(*, ticker: str, question: str, reason: str, related: list[str]) -> dict[str, Any]:
    return {
        "question_id": new_id("brq"),
        "ticker": str(ticker).upper(),
        "question": compact_text(question, 240),
        "reason": compact_text(reason, 400),
        "related_objects": related,
        "status": "open",
    }


def evaluate_brain_changes(
    *,
    ticker: str,
    observations: list[dict[str, Any]] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    brain: dict[str, Any] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Gate writes. Approved proposals may be stored; rejected ones cannot mutate Brain."""
    symbol = str(ticker).upper()
    context = dict(brain or {})
    context["ticker"] = symbol
    existing_facts = list(context.get("existing_facts") or [])
    shadows: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    observations_kept: list[dict[str, Any]] = []
    fingerprints: list[str] = list(context.get("event_fingerprints") or [])
    identities: list[str] = list(context.get("event_identities") or [])
    duplicate_count = 0

    for raw in observations or []:
        item = dict(raw)
        item["fact_reliability"] = item.get("fact_reliability") or fact_reliability(item)
        kind = str(item.get("kind") or item.get("source_kind") or "news")
        title = compact_text(item.get("title") or item.get("fact") or item.get("statement") or "", 160)
        identity = _observation_identity(item)
        fingerprint = item.get("fingerprint") or make_event_fingerprint({"title": title, "url": item.get("url"), "subject": item.get("subject") or title})
        if (
            item.get("duplicate")
            or fingerprint in fingerprints
            or identity in identities
            or news_is_duplicate(item, existing_facts)
        ):
            duplicate_count += 1
            continue
        fingerprints.append(fingerprint)
        identities.append(identity)
        existing_facts.append(title)
        item["fingerprint"] = fingerprint
        item["kind"] = kind
        if kind == "price" and not item.get("fundamental_evidence_ids"):
            observations_kept.append({**item, "layer": "observation"})
            questions.append(
                _research_question(
                    ticker=symbol,
                    question="What is the market pricing that the current Brain does not explain?",
                    reason=item.get("reason") or "Price moved without new fundamental evidence.",
                    related=[item.get("object_id") or "price", *(item.get("related_objects") or [])],
                )
            )
            continue
        if should_enter_shadow(item) or is_weak_signal(item):
            shadow = normalize_shadow(item, ticker=symbol)
            shadows.append(shadow)
            if is_weak_signal(item):
                questions.append(
                    _research_question(
                        ticker=symbol,
                        question=f"Can we confirm: {shadow['name']}?",
                        reason="Weak signal is a research question, not a conclusion.",
                        related=[shadow["shadow_id"]],
                    )
                )
            continue
        observations_kept.append(item)

    context["existing_facts"] = existing_facts
    context["event_fingerprints"] = fingerprints
    context["event_identities"] = identities
    normalized = [normalize_proposal(row, ticker=symbol) for row in (proposals or []) if isinstance(row, dict)]
    budget = change_scope(normalized)

    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for proposal in normalized:
        if proposal.get("duplicate"):
            proposal["decision"] = "reject"
            proposal["rules"] = [{"rule": "duplicate_news_cannot_version_claim", "reason": "Duplicate news cannot create a new Claim version."}]
            proposal["reason_code"] = "duplicate_news_cannot_version_claim"
            rejected.append(proposal)
            continue
        hits = constitution_violations(proposal, brain=context)
        if budget["requires_review"]:
            proposal["decision"] = "requires_review"
            budget_rule = {
                "rule": "abnormal_change_scope_requires_review",
                "reason": "Ordinary event cannot auto-commit a large Brain rewrite.",
            }
            proposal["rules"] = [budget_rule, *hits]
            proposal["reason_code"] = "abnormal_change_scope_requires_review"
            review.append(proposal)
            continue
        if hits:
            proposal["decision"] = "reject"
            proposal["rules"] = hits
            proposal["reason_code"] = str(hits[0].get("rule") or "constitution_reject")
            if any(row["rule"] == "low_confidence_cannot_modify_current_state" for row in hits):
                payload = dict(proposal.get("to_payload") or {})
                shadows.append(normalize_shadow({**proposal, **payload}, ticker=symbol))
            if any(row["rule"] in {"unexplained_price_is_not_mispricing", "price_cannot_modify_fundamental_claim"} for row in hits):
                questions.append(
                    _research_question(
                        ticker=symbol,
                        question="What is the market pricing that the current Brain does not explain?",
                        reason="Price move is unexplained; do not conclude mispricing.",
                        related=[proposal.get("object_id") or "price"],
                    )
                )
            if any(row["rule"] == "weak_signal_becomes_research_question" for row in hits):
                questions.append(
                    _research_question(
                        ticker=symbol,
                        question=f"Can we confirm the proposed {proposal.get('object_type')} change?",
                        reason="Weak signal is a research question, not a conclusion.",
                        related=[proposal.get("object_id") or proposal.get("object_type") or ""],
                    )
                )
            if any(row["rule"] in {"news_cannot_modify_core_claim", "claim_slower_than_driver"} for row in hits):
                claim = dict(proposal.get("from_payload") or {})
                direction = "oppose" if str((proposal.get("to_payload") or {}).get("status") or "") in {"challenged", "contradicted"} else "support"
                proposal["inertia"] = accumulate_claim_evidence(claim, direction=direction)
            rejected.append(proposal)
            continue
        proposal["decision"] = "approve"
        approved.append(proposal)

    shadows = _unique_by(shadows, "name")
    questions = _unique_by(questions, "question")

    committed: list[dict[str, Any]] = []
    auto_commit = bool(budget["auto_commit_allowed"]) and not review
    if store is not None:
        for item in observations_kept:
            if hasattr(store, "insert_news"):
                store.insert_news(
                    {
                        "ticker": symbol,
                        "layer": "contextual",
                        "title": item.get("title") or "",
                        "url": item.get("url"),
                        "new_fact": item.get("fact") or item.get("statement"),
                        "reason": item.get("reason") or "",
                        "claim_version_changed": False,
                    }
                )
        for shadow in shadows:
            if hasattr(store, "upsert_shadow"):
                stored_shadow = store.upsert_shadow(shadow)
                committed.append({"kind": "shadow", "shadow_id": stored_shadow.get("shadow_id"), "name": stored_shadow.get("name")})
        for question in questions:
            if hasattr(store, "insert_question"):
                stored_q = store.insert_question(
                    {
                        "ticker": symbol,
                        "question": question["question"],
                        "why_it_matters": question["reason"],
                        "status": question["status"],
                        "related_claim_id": None,
                        "related_objects": question.get("related_objects") or [],
                    }
                )
                committed.append({"kind": "question", "question_id": stored_q.get("question_id")})
        persistable = approved if auto_commit else []
        for proposal in persistable + rejected + review:
            if not proposal.get("related_objects"):
                related = [proposal.get("object_type") or "", proposal.get("object_id") or ""]
                proposal["related_objects"] = [item for item in related if item]
            if hasattr(store, "insert_proposal"):
                stored_p = store.insert_proposal({**proposal, "decision": proposal["decision"]})
                committed.append(
                    {
                        "kind": "proposal",
                        "proposal_id": stored_p.get("proposal_id"),
                        "object_id": proposal.get("object_id"),
                        "decision": proposal.get("decision"),
                        "reason_code": proposal.get("reason_code") or "",
                    }
                )
                if proposal.get("decision") == "approve" and auto_commit:
                    if proposal.get("object_type") in {"shadow_state", "shadow"} and hasattr(store, "upsert_shadow"):
                        payload = dict(proposal.get("to_payload") or {})
                        store.upsert_shadow({**payload, "ticker": symbol, "source_kind": proposal.get("source_kind")})
                    if proposal.get("object_type") in {"research_question", "question"} and hasattr(store, "insert_question"):
                        store.insert_question(
                            {
                                "ticker": symbol,
                                "question": (proposal.get("to_payload") or {}).get("question") or proposal.get("reason") or "",
                                "why_it_matters": proposal.get("reason") or "",
                                "related_objects": proposal.get("related_objects") or [],
                            }
                        )
                    if hasattr(store, "insert_history"):
                        store.insert_history(
                            {
                                "ticker": symbol,
                                "object_type": proposal.get("object_type"),
                                "object_id": proposal.get("object_id"),
                                "from_payload": proposal.get("from_payload") or {},
                                "to_payload": proposal.get("to_payload") or {},
                                "reason": proposal.get("reason") or "",
                            }
                        )

    for row in approved + rejected + review:
        if row.get("decision") not in PROPOSAL_DECISIONS:
            row["decision"] = "reject"

    return {
        "ticker": symbol,
        "observations": observations_kept,
        "shadows": shadows,
        "questions": questions,
        "proposals": normalized,
        "approved": approved,
        "rejected": rejected,
        "requires_review": review,
        "budget": budget,
        "duplicate_count": duplicate_count,
        "committed": committed,
        "auto_commit_allowed": auto_commit,
        "current_state_unchanged": not any(
            row.get("object_type") in {"state", "company_state", "industry_state", "macro_state"} and row.get("decision") == "approve"
            for row in (approved if auto_commit else [])
        ),
        "core_claims_unchanged": not any(
            row.get("object_type") in {"claim", "core_claim"} and row.get("decision") == "approve"
            for row in (approved if auto_commit else [])
        ),
        "claim_versions_created": 0,
    }


def _unique_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        token = str(row.get(key) or "")
        if token in seen:
            continue
        seen.add(token)
        out.append(row)
    return out
