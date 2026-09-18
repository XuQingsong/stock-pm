"""Now Chain: four PM questions the Brain must be able to answer after an event.

1. What happened
2. Why it affects this company
3. Through what path it reaches Driver / Claim
4. What the market is actually trading

Deterministic. LLM may propose market_attention; this assembler decides the answers.
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


def _market_line(
    *,
    event: dict[str, Any] | None,
    attentions: list[dict[str, Any]] | None,
    alignment: dict[str, Any],
) -> str:
    status = str(alignment.get("alignment") or "unknown")
    if status == "unknown":
        return "Unknown — this update has no tape evidence, so the Brain does not guess what the market is trading."
    if attentions:
        statement = compact_text((attentions[0] or {}).get("statement") or (attentions[0] or {}).get("reason") or "", 200)
        if statement:
            if status == "unexplained":
                return f"Tape attention: {statement} Brain path does not justify treating this as mispricing."
            return f"Market appears to be trading: {statement}"
    if event_has_tape(event) and status == "unexplained":
        return "A price move is unexplained by the current causal path. That is not mispricing."
    if event_has_tape(event):
        return compact_text(
            (event or {}).get("price_reaction") or alignment.get("reason") or "Tape moved; Claims stay unchanged.",
            200,
        )
    return compact_text(alignment.get("reason") or "Market attention is not a conclusion.", 200)


def build_now_chain(
    *,
    event: dict[str, Any] | None,
    extract: dict[str, Any] | None = None,
    exposures: list[dict[str, Any]] | None = None,
    transmission: dict[str, Any] | None = None,
    causal_gaps: list[dict[str, Any]] | None = None,
    market_attentions: list[dict[str, Any]] | None = None,
    questions: list[dict[str, Any]] | None = None,
    material: bool | None = None,
    stopped: str | None = None,
) -> dict[str, Any]:
    item = dict(event or {})
    extracted = dict(extract or {})
    title = compact_text(item.get("title") or extracted.get("event") or extracted.get("fact") or "", 160)
    fact = compact_text(item.get("fact") or extracted.get("fact") or title, 240)
    reliability = str(item.get("fact_reliability") or extracted.get("fact_reliability") or "")
    exposures = list(exposures or [])
    gaps = list(causal_gaps or [])
    attentions = list(market_attentions or [])
    why = "; ".join(_exposure_line(row) for row in exposures[:3]) if exposures else "No company exposure is linked yet."
    path_text, can_driver, can_claim = _path_line(transmission, gaps)
    alignment = align_market_with_path(event=item, attentions=attentions, transmission=transmission, gaps=gaps)
    market_text = _market_line(event=item, attentions=attentions, alignment=alignment)
    happened = title or fact or "No event."
    if stopped:
        happened = f"{happened} ({stopped})" if happened else stopped
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
            "question": "市场现在到底在交易什么",
            "answer": market_text,
            "alignment": alignment.get("alignment"),
            "cannot_conclude_mispricing": bool(alignment.get("cannot_conclude_mispricing", True)),
            "attentions": [
                {
                    "attention_id": row.get("attention_id"),
                    "name": row.get("name"),
                    "statement": row.get("statement"),
                    "related_objects": row.get("related_objects") or [],
                }
                for row in attentions[:3]
            ],
            "research_questions": [
                compact_text(row.get("question") or "", 160)
                for row in (questions or [])
                if "market" in str(row.get("question") or "").lower() or "pricing" in str(row.get("question") or "").lower()
            ][:3],
        },
        "answers": {
            "what_happened": happened or fact,
            "why_it_affects_company": why,
            "path_to_driver_claim": path_text,
            "what_market_is_trading": market_text,
        },
    }
