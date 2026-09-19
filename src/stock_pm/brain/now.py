"""Now Chain: four PM questions the Brain must be able to answer after an event.

1. What happened
2. Why it affects this company
3. Through what path it reaches Driver / Claim
4. How the market currently understands it

Deterministic. LLM may propose market objects; this assembler decides the answers.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text

from .market import align_market_with_path, event_has_tape


def _exposure_line(row: dict[str, Any]) -> str:
    subject = compact_text(row.get("subject") or row.get("ticker") or "", 40)
    obj = compact_text(row.get("object_name") or row.get("exposure_type") or "", 80)
    mechanism = compact_text(row.get("mechanism") or row.get("reason") or "", 160)
    if mechanism:
        return mechanism
    if subject and obj:
        return f"{subject} is exposed to {obj}."
    return compact_text(row.get("exposure_type") or "exposure", 80)


def _path_line(transmission: dict[str, Any] | None, gaps: list[dict[str, Any]] | None) -> tuple[str, bool, bool]:
    successful = list((transmission or {}).get("successful") or [])
    blocked = list((transmission or {}).get("blocked") or [])
    if successful:
        nodes = successful[0].get("nodes") or []
        drawn = " → ".join(str(node) for node in nodes[:8]) if nodes else "supported causal path"
        return f"Event can travel a supported path: {drawn}.", True, True
    if blocked:
        reason = blocked[0].get("reason") or "transmission_stop"
        return f"Transmission stops on an unsupported edge ({reason}). Downstream Driver / Claim cannot be rewritten.", False, False
    if gaps:
        question = compact_text((gaps[0] or {}).get("question") or "a missing relationship", 160)
        return f"No complete causal path. Research first: {question}", False, False
    return "No targeted causal path is available for this event.", False, False


def _understand_line(
    *,
    attentions: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    alignment: dict[str, Any],
    unresolved: bool,
    explanation: dict[str, Any] | None = None,
    divergences: list[dict[str, Any]] | None = None,
) -> str:
    parts: list[str] = []
    if attentions:
        statement = compact_text((attentions[0] or {}).get("statement") or (attentions[0] or {}).get("name") or "", 160)
        if statement:
            parts.append(f"Attention: {statement}")
    if expectations:
        row = expectations[0]
        parts.append(
            f"Expectation: actual {row.get('actual')} vs expected {row.get('expected')} ({row.get('comparison')}, {row.get('trend')})"
        )
    live = [row for row in hypotheses if str(row.get("status") or "") != "retired"][:4]
    if live:
        labels = [compact_text(row.get("hypothesis") or row.get("canonical_key") or "", 80) for row in live]
        labels = [item for item in labels if item]
        numbered = "; ".join(f"{idx}. {label}" for idx, label in enumerate(labels, start=1))
        parts.append(f"Candidate drivers: {numbered}.")
        if len(live) > 1:
            parts.append("Which driver dominates is not established.")
    peer = (explanation or {}).get("peer_pattern")
    parts.append(f"Price / Peer Alignment: {peer or alignment.get('alignment') or 'unknown'}")
    conf = "low" if unresolved or any(str(row.get("status") or "") == "unresolved" for row in hypotheses) else (
        "medium" if hypotheses or expectations or attentions else "low"
    )
    parts.append(f"Confidence: {conf}")
    if explanation and explanation.get("feedback"):
        parts.append(f"Price Feedback: {explanation.get('feedback')}")
    live_div = [row for row in (divergences or []) if str(row.get("status") or "") in {"open", "partially_explained", "resolved"}]
    if live_div:
        parts.append(f"Divergence: {live_div[0].get('status')}")
    if unresolved or any(str(row.get("status") or "") == "unresolved" for row in hypotheses) or any(
        str(row.get("status") or "") == "open" for row in (divergences or [])
    ):
        question = (explanation or {}).get("unresolved_question") or (
            (live_div[0].get("unresolved_question") if live_div else "") or "what is the market pricing that the Brain does not explain?"
        )
        parts.append(f"Unresolved: {question}")
    if not parts:
        if alignment.get("alignment") == "unknown" and not event_has_tape(None):
            return "Unknown — this update has no tape evidence, so the Brain does not guess a market driver."
        return compact_text(alignment.get("reason") or "Market understanding is not a conclusion.", 200)
    return " ".join(parts)


def build_now_chain(
    *,
    event: dict[str, Any] | None,
    extract: dict[str, Any] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    transmission: dict[str, Any] | None = None,
    causal_gaps: list[dict[str, Any]] | None = None,
    market_attentions: list[dict[str, Any]] | None = None,
    expectations: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    questions: list[dict[str, Any]] | None = None,
    material: bool | None = None,
    stopped: str | None = None,
    unresolved: bool | None = None,
    explanation: dict[str, Any] | None = None,
    divergences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = dict(event or {})
    extracted = dict(extract or {})
    title = compact_text(item.get("title") or extracted.get("event") or extracted.get("fact") or "", 160)
    fact = compact_text(item.get("fact") or extracted.get("fact") or title, 240)
    reliability = str(item.get("fact_reliability") or extracted.get("fact_reliability") or "")
    exposures = list(exposures or [])
    gaps = list(causal_gaps or [])
    attentions = list(market_attentions or [])
    expectation_rows = list(expectations or [])
    hypothesis_rows = list(hypotheses or [])
    why = "; ".join(_exposure_line(row) for row in exposures[:3]) if exposures else "No company exposure is linked yet."
    path_text, can_driver, can_claim = _path_line(transmission, gaps)
    alignment = align_market_with_path(event=item, attentions=attentions, transmission=transmission, gaps=gaps)
    divergence_rows = list(divergences or [])
    open_unresolved = bool(unresolved) or any(str(row.get("status") or "") == "unresolved" for row in hypothesis_rows) or any(
        str(row.get("status") or "") == "open" for row in divergence_rows
    )
    market_text = _understand_line(
        attentions=attentions,
        expectations=expectation_rows,
        hypotheses=hypothesis_rows,
        alignment=alignment,
        unresolved=open_unresolved,
        explanation=explanation,
        divergences=divergence_rows,
    )
    happened = title or fact or "No event."
    if stopped:
        happened = f"{happened} ({stopped})" if happened else stopped
    conf = "low" if open_unresolved or reliability in {"rumor", "signal"} else ("medium" if hypothesis_rows or expectation_rows else "low")
    return {
        "what_happened": {
            "question": "发生了什么",
            "answer": happened or fact,
            "fact": fact,
            "event_type": item.get("event_type") or extracted.get("event_type"),
            "entities": list(item.get("entities") or extracted.get("entities") or [])[:8],
            "fact_reliability": reliability,
            "material": bool(material if material is not None else item.get("material")),
            "stopped": stopped,
        },
        "why_it_affects_company": {
            "question": "为什么会影响公司",
            "answer": why,
            "exposures": [
                {
                    "exposure_id": row.get("exposure_id"),
                    "subject": row.get("subject"),
                    "object_name": row.get("object_name"),
                    "direction": row.get("direction"),
                    "magnitude": row.get("magnitude"),
                    "mechanism": row.get("mechanism") or row.get("reason"),
                }
                for row in exposures[:4]
            ],
        },
        "path_to_driver_claim": {
            "question": "通过什么路径影响 Driver / Claim",
            "answer": path_text,
            "can_affect_driver": can_driver,
            "can_affect_claim": can_claim,
            "successful": list((transmission or {}).get("successful") or [])[:3],
            "blocked": list((transmission or {}).get("blocked") or [])[:3],
            "gaps": gaps[:3],
        },
        "what_market_is_trading": {
            "question": "市场现在怎么理解它",
            "answer": market_text,
            "alignment": alignment.get("alignment"),
            "cannot_conclude_mispricing": bool(alignment.get("cannot_conclude_mispricing", True)),
            "confidence": conf,
            "attentions": [
                {
                    "attention_id": row.get("attention_id"),
                    "name": row.get("name"),
                    "statement": row.get("statement"),
                    "related_objects": row.get("related_objects") or [],
                }
                for row in attentions[:3]
            ],
            "expectation": {
                "actual": (expectation_rows[0] or {}).get("actual") if expectation_rows else None,
                "expected": (expectation_rows[0] or {}).get("expected") if expectation_rows else None,
                "comparison": (expectation_rows[0] or {}).get("comparison") if expectation_rows else None,
                "trend": (expectation_rows[0] or {}).get("trend") if expectation_rows else None,
                "confidence": (expectation_rows[0] or {}).get("confidence") if expectation_rows else None,
                "last_material_change": (expectation_rows[0] or {}).get("last_material_change") if expectation_rows else None,
            }
            if expectation_rows
            else None,
            "candidate_drivers": [
                {
                    "canonical_key": row.get("canonical_key"),
                    "hypothesis": row.get("hypothesis"),
                    "status": row.get("status"),
                    "confidence": row.get("confidence"),
                }
                for row in hypothesis_rows[:5]
            ],
            "unresolved": open_unresolved,
            "price_feedback": (explanation or {}).get("feedback"),
            "explanation_grade": (explanation or {}).get("grade"),
            "price_peer_alignment": (explanation or {}).get("peer_pattern") or alignment.get("alignment"),
            "divergence": {
                "status": (divergence_rows[0] or {}).get("status") if divergence_rows else None,
                "grade": (divergence_rows[0] or {}).get("explanation_grade") if divergence_rows else None,
                "divergence_id": (divergence_rows[0] or {}).get("divergence_id") if divergence_rows else None,
                "signature": (divergence_rows[0] or {}).get("signature") if divergence_rows else None,
            }
            if divergence_rows
            else None,
            "research_questions": [
                compact_text(row.get("question") or "", 160)
                for row in (questions or [])
                if row.get("question")
            ][:4],
        },
        "answers": {
            "what_happened": happened or fact,
            "why_it_affects_company": why,
            "path_to_driver_claim": path_text,
            "what_market_is_trading": market_text,
        },
    }
