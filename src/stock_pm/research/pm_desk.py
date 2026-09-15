"""Homepage compression of PM LLM reasoning. Old assumption/ledger trees stay in detail."""

from __future__ import annotations

import re
from typing import Any

from .llm_reason import compact_text


def _text(value: Any, limit: int = 400) -> str:
    return compact_text(value, limit)


def _lead(value: Any, limit: int = 400) -> str:
    text = compact_text(value, 800)
    parts = [chunk.strip() for chunk in re.split(r"(?<=[.。!?！？])\s+", text) if chunk.strip()]
    first = parts[0] if parts else text
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _evidence_index(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        key = str(row.get("id") or "")
        if key:
            out[key] = row
    return out


def _gaps(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    parts = [str(item) for item in (value or [])]
    if parts and all(len(part.strip()) <= 1 for part in parts):
        joined = "".join(parts).strip()
        return [joined] if joined else []
    return [part.strip() for part in parts if part.strip() and len(part.strip()) > 1][:4]


def _hydrate(items: list[Any] | None, index: dict[str, dict[str, Any]], *, why_key: str, limit: int) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for item in items or []:
        inline_fact = ""
        if isinstance(item, dict):
            eid = str(item.get("evidence_id") or item.get("id") or "").strip()
            why = _text(item.get(why_key) or item.get("why_it_changes_thesis") or item.get("why_not") or item.get("why") or "", 220)
            inline_fact = item.get("fact") or item.get("excerpt") or ""
        else:
            eid = str(item).strip()
            why = ""
        if not eid or eid in seen:
            continue
        seen.add(eid)
        row = index.get(eid) or {}
        out.append(
            {
                "evidence_id": eid,
                "fact": _text(inline_fact or row.get("fact") or row.get("excerpt") or "", 280),
                "why": why,
                "source": row.get("source") or (item.get("source") if isinstance(item, dict) else None),
                "source_time": row.get("source_time"),
                "source_url": row.get("source_url"),
            }
        )
        if len(out) >= limit:
            break
    return out


def _variables(rows: list[Any] | None, index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name") or item.get("variable") or "", 80)
        if not name:
            continue
        out.append(
            {
                "name": name,
                "why_decisive": _text(item.get("why_decisive") or "", 240),
                "current_view": _text(item.get("current_view") or "", 240),
                "sensitivity": _text(item.get("sensitivity") or "", 200),
                "next_check": _text(item.get("next_check") or "", 160),
                "evidence": _hydrate(item.get("evidence_ids") or item.get("evidence") or [], index, why_key="why", limit=4),
            }
        )
        if len(out) >= 3:
            break
    return out


def _disagreement(rows: list[Any] | None) -> list[dict[str, Any]]:
    out = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "pm_believes": _text(item.get("pm_believes") or "", 240),
                "market_appears_to_price": _text(item.get("market_appears_to_price") or "", 240),
                "why_pm_differs": _text(item.get("why_pm_differs") or "", 240),
                "evidence_that_would_prove_market_right": _text(
                    item.get("evidence_that_would_prove_market_right") or "", 240
                ),
            }
        )
        if len(out) >= 2:
            break
    return out


def _hypotheses(rows: list[Any] | None) -> list[dict[str, Any]]:
    out = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        statement = _text(item.get("statement") or "", 280)
        if not statement:
            continue
        out.append(
            {
                "statement": statement,
                "probability_band": _text(item.get("probability_band") or "", 40),
                "how_to_test": _text(item.get("how_to_test") or "", 200),
                "impact_if_true": _text(item.get("impact_if_true") or "", 200),
                "missing_evidence": _gaps(item.get("missing_evidence")),
            }
        )
        if len(out) >= 4:
            break
    return out


def _counterfactuals(rows: list[Any] | None) -> list[dict[str, Any]]:
    out = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        premise = _text(item.get("if") or item.get("statement") or "", 240)
        if not premise:
            continue
        out.append(
            {
                "if": premise,
                "thesis_impact": _text(item.get("thesis_impact") or "", 240),
                "eps_or_valuation_direction": _text(item.get("eps_or_valuation_direction") or "", 160),
                "what_to_recompute": _text(item.get("what_to_recompute") or "", 160),
            }
        )
        if len(out) >= 4:
            break
    return out


def build_pm_desk(
    *,
    thesis: dict[str, Any] | None,
    snapshot: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """First-screen object. Caps: 3 variables, 5 thesis-changing facts, 2 disagreements."""
    thesis = thesis or {}
    snapshot = snapshot or {}
    quality = thesis.get("research_quality") if isinstance(thesis.get("research_quality"), dict) else {}
    raw = quality.get("pm_reasoning") if isinstance(quality.get("pm_reasoning"), dict) else {}
    cal = {}
    valuation = snapshot.get("valuation") if isinstance(snapshot.get("valuation"), dict) else {}
    if isinstance(valuation.get("calibration_json"), dict):
        cal = valuation["calibration_json"]
        if not raw and isinstance(cal.get("pm_reasoning"), dict):
            raw = cal["pm_reasoning"]
    golden = quality.get("golden_answers") if isinstance(quality.get("golden_answers"), dict) else {}
    if not golden:
        golden = raw.get("golden_answers") if isinstance(raw.get("golden_answers"), dict) else {}
    index = _evidence_index(evidence if evidence is not None else snapshot.get("evidence"))
    source = str(raw.get("source") or "")
    if source not in {"llm", "deterministic_fallback"}:
        source = "llm" if raw.get("decisive_variables") or raw.get("core_contradiction") else "deterministic_fallback"
    low = (
        raw.get("low_value_evidence")
        or raw.get("non_thesis_changing_evidence")
        or raw.get("looks_important_but_does_not_change_thesis")
        or []
    )
    most_wrong = _text(
        raw.get("most_likely_wrong") or golden.get("most_likely_error") or raw.get("what_could_make_me_wrong") or "",
        320,
    )
    change_mind = _text(
        raw.get("what_would_change_my_mind")
        or golden.get("evidence_that_would_change_the_call")
        or raw.get("thesis_invalidation")
        or "",
        320,
    )
    conclusion = _lead(raw.get("core_thesis") or thesis.get("core_thesis") or "")
    contradiction = _text(raw.get("core_contradiction") or golden.get("core_contradiction") or "", 220)
    variables = _variables(raw.get("decisive_variables"), index)
    changing = _hydrate(
        raw.get("top_thesis_changing_evidence") or raw.get("top_5_thesis_changing_evidence") or [],
        index,
        why_key="why_it_changes_thesis",
        limit=5,
    )
    competing = _hypotheses(raw.get("competing_hypotheses") or snapshot.get("competing_hypotheses"))
    evidence_count = max(len(index), int(raw.get("evidence_count") or 0) or 0)
    return {
        "source": source,
        "compressed": source == "llm" and bool(variables or changing),
        "evidence_count": evidence_count,
        "conclusion": conclusion,
        "core_contradiction": contradiction,
        "decisive_variables": variables,
        "market_disagreement": _disagreement(raw.get("market_disagreement") or golden.get("market_disagreement")),
        "most_likely_wrong": most_wrong,
        "top_thesis_changing_evidence": changing,
        "low_value_evidence": _hydrate(low, index, why_key="why_not", limit=3),
        "non_thesis_changing_evidence": _hydrate(low, index, why_key="why_not", limit=3),
        "next_information_to_seek": _text(raw.get("next_information_to_seek") or "", 240),
        "what_would_change_my_mind": change_mind,
        "competing_hypotheses": competing,
        "counterfactuals": _counterfactuals(raw.get("counterfactuals")),
        "llm_audit": raw.get("llm_audit") if isinstance(raw.get("llm_audit"), dict) else {},
    }
