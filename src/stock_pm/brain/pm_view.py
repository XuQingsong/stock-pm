"""PM View / Investment Snapshot.

Read-only assembly of a persisted Brain. No GLM, no research pack rebuild,
no architecture change. Answers four PM questions on one payload:

1. What is the live investment logic? (Core Claims)
2. What actually changed? (State / Driver / Expectation / Claim deltas)
3. What might the market be trading? (Expectation / hypotheses / divergence + Now Chain)
4. What must be verified next? (open research questions)
"""

from __future__ import annotations

import re
from typing import Any

from stock_pm.research.llm_reason import compact_text

from .bootstrap import brain_has_baseline, brain_lifecycle
from .expectation import coerce_expectation_comparison
from .investment import investment_snapshot
from .now import build_now_chain
from .types import CORE_CLAIM_MAX

DELTA_TYPES = {
    "state": "State",
    "company_state": "State",
    "industry_state": "State",
    "macro_state": "State",
    "driver": "Driver",
    "value_driver": "Driver",
    "expectation": "Expectation",
    "expectation_state": "Expectation",
    "claim": "Claim",
    "core_claim": "Claim",
}

WATCHED_FIELDS = {
    "State": ("name", "statement", "direction", "confidence", "qualitative_state", "current_value", "status"),
    "Driver": ("name", "current_state", "confidence", "status", "why_it_matters"),
    "Expectation": ("name", "actual", "expected", "comparison", "trend", "last_material_change", "reason"),
    "Claim": ("title", "statement", "status", "confidence", "lifecycle"),
}

SKIP_KEYS = {
    "updated_at",
    "created_at",
    "last_reviewed_at",
    "run_id",
    "snapshot_id",
    "history_id",
    "match_action",
    "evidence_set_id",
}

STRENGTH_RANK = {"strong": 3, "high": 3, "medium": 2, "moderate": 2, "weak": 1, "low": 1}
IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
CLOSED_QUESTION = {"closed", "answered", "resolved", "retired", "done"}
RETIRED_HYPOTHESIS = {"retired", "rejected", "closed"}
UNRESOLVED_DIVERGENCE = {"open", "partially_explained"}
WHAT_CHANGED_LIMIT = 8
QUESTION_LIMIT = 5
HYPOTHESIS_LIMIT = 4
EXPECTATION_LIMIT = 4
NOW_HYPOTHESIS_LIMIT = 3
NOW_EXPECTATION_LIMIT = 2
CLAIM_STATEMENT_WIDTH = 200

CLAIM_STATUS_RANK = {
    "challenged": 0,
    "contradicted": 0,
    "partially_supported": 1,
    "strongly_supported": 2,
    "emerging": 3,
    "unverified": 4,
    "background": 5,
    "closed": 6,
}
PLACEHOLDER_HYP_KEYS = {"other", "unresolved"}
PLACEHOLDER_HYP_TEXT = {
    "other",
    "market driver is unresolved",
    "company-specific concern",
    "sector / macro move",
    "sector wide semiconductor selloff",
}
PLACEHOLDER_EXPECTATION_NAMES = {"expectation", "rumor_expectation"}
LOW_VALUE_QUESTION = (
    re.compile(r"^is there a missing (market driver|expectation|exposure|causal edge)\b"),
    re.compile(r"^is a missing (market driver|expectation variable|exposure|causal edge)\b"),
    re.compile(r"^brain lacks\b"),
    re.compile(r"^cannot transmit\b"),
    re.compile(r"^no financial link\b"),
    re.compile(r"^no core claim exists\b"),
    re.compile(r"^state-to-driver link is missing\b"),
    re.compile(r"^what .+ links .+ to "),
    re.compile(r"^no transmittable path\b"),
)


def _rows(store: Any, method: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    if store is None or not hasattr(store, method):
        return []
    return list(getattr(store, method)(*args, **kwargs) or [])


def _sort_time(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _norm_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _token_overlap(left: str, right: str) -> float:
    a = set(left.split())
    b = set(right.split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _low_value_question(row: dict[str, Any], *, has_claims: bool) -> bool:
    raw = str(row.get("question") or "").strip().lower()
    question = _norm_text(row.get("question"))
    why = _norm_text(row.get("why_it_matters"))
    if not question:
        return True
    if raw.startswith("can we confirm:"):
        return True
    if "unsupported causal edge" in why:
        return True
    if has_claims and question.startswith("no core claim exists"):
        return True
    return any(pattern.search(question) for pattern in LOW_VALUE_QUESTION)


def _question_rank(row: dict[str, Any]) -> tuple[int, int, str]:
    text = str(row.get("question") or "")
    score = 0
    if re.search(r"\d", text):
        score += 2
    lowered = text.lower()
    if any(token in lowered for token in ("google", "anthropic", "openai", "eps", "revenue", "cpo", "eml", "coherent", "marvell", "q3", "q4", "guidance")):
        score += 1
    return (
        PRIORITY_RANK.get(str(row.get("priority") or "medium").lower(), 1),
        -score,
        _sort_time(row, "created_at"),
    )


def _placeholder_hypothesis(row: dict[str, Any]) -> bool:
    key = str(row.get("canonical_key") or "").strip().lower()
    text = str(row.get("hypothesis") or row.get("name") or "").strip().lower()
    if key in PLACEHOLDER_HYP_KEYS or text in PLACEHOLDER_HYP_TEXT:
        return True
    return bool(key) and "_" in key and _norm_text(text) == _norm_text(key.replace("_", " "))


def _hypothesis_rank(row: dict[str, Any]) -> tuple[int, int]:
    confidence = {"high": 0, "medium": 1, "low": 2}.get(str(row.get("confidence") or "low").lower(), 2)
    status = {"active": 0, "open": 1, "unresolved": 1, "candidate": 2}.get(str(row.get("status") or "").lower(), 3)
    return (confidence, status)


def _placeholder_expectation(row: dict[str, Any]) -> bool:
    name = str(row.get("name") or row.get("subject") or "").strip().lower()
    if not name or name in PLACEHOLDER_EXPECTATION_NAMES:
        return True
    return row.get("actual") is None and row.get("expected") is None


def _expectation_rank(row: dict[str, Any]) -> tuple[int, int]:
    numbered = 0 if row.get("actual") is not None or row.get("expected") is not None else 1
    known = 0 if str(row.get("comparison") or "") not in {"", "unknown"} else 1
    return (numbered, known)


def _dedup_questions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: list[str] = []
    for row in rows:
        norm = _norm_text(row.get("question"))
        if any(_token_overlap(norm, prev) >= 0.72 for prev in seen):
            continue
        seen.append(norm)
        out.append(row)
    return out


def _evidence_index(store: Any, ticker: str, research: Any | None = None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _rows(store, "list_evidence", ticker):
        eid = str(row.get("id") or row.get("evidence_id") or "")
        if eid:
            index[eid] = row
    if research is not None and getattr(research, "store", None) is not None:
        for row in _rows(research.store, "list_evidence", ticker):
            eid = str(row.get("id") or row.get("evidence_id") or "")
            if eid and eid not in index:
                index[eid] = row
    return index


def _brief_evidence(row: dict[str, Any] | None, link: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not row and not link:
        return None
    fact = compact_text(
        (row or {}).get("fact")
        or (row or {}).get("excerpt")
        or (row or {}).get("statement")
        or (link or {}).get("reason")
        or "",
        240,
    )
    if not fact and not (link or {}).get("evidence_id") and not (row or {}).get("id"):
        return None
    return {
        "id": (row or {}).get("id") or (row or {}).get("evidence_id") or (link or {}).get("evidence_id"),
        "fact": fact or None,
        "source": (row or {}).get("source"),
        "source_time": (row or {}).get("source_time"),
        "strength": (link or {}).get("strength"),
        "reason": compact_text((link or {}).get("reason") or "", 200) or None,
    }


def _strongest_link(
    links: list[dict[str, Any]],
    direction: str,
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ranked = [row for row in links if str(row.get("direction") or "") == direction]
    ranked.sort(key=lambda row: STRENGTH_RANK.get(str(row.get("strength") or "").lower(), 0), reverse=True)
    if not ranked:
        return None
    top = ranked[0]
    return _brief_evidence(evidence.get(str(top.get("evidence_id") or "")), top)


def _claim_recent_change(store: Any, ticker: str, claim: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
    claim_id = str(claim.get("claim_id") or "")
    versions = _rows(store, "list_versions", claim_id) if claim_id else []
    if versions:
        latest = versions[-1]
        old_status = latest.get("old_status")
        new_status = latest.get("new_status") or latest.get("status")
        old_statement = latest.get("old_statement")
        new_statement = latest.get("new_statement") or latest.get("statement")
        if old_status or latest.get("reason_for_change") or (old_statement and old_statement != new_statement):
            return {
                "kind": "version",
                "from_status": old_status,
                "to_status": new_status,
                "reason": compact_text(latest.get("reason_for_change") or "", 240) or None,
                "created_at": latest.get("created_at"),
            }
    for row in reversed(history):
        if str(row.get("object_id") or "") != claim_id:
            continue
        if DELTA_TYPES.get(str(row.get("object_type") or "")) != "Claim":
            continue
        deltas = _field_deltas(row.get("from_payload") or {}, row.get("to_payload") or {}, "Claim")
        if not deltas:
            continue
        return {
            "kind": "history",
            "from_status": (row.get("from_payload") or {}).get("status"),
            "to_status": (row.get("to_payload") or {}).get("status"),
            "reason": compact_text(row.get("reason") or "", 240) or None,
            "created_at": row.get("created_at"),
            "deltas": deltas,
        }
    return None


def _core_claims(store: Any, ticker: str, evidence: dict[str, dict[str, Any]], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .product_read import is_fundamental_core_claim

    claims = [row for row in _rows(store, "list_active_claims", ticker) if is_fundamental_core_claim(row)]
    claims.sort(
        key=lambda row: (
            CLAIM_STATUS_RANK.get(str(row.get("final_status") or row.get("status") or "").lower(), 3),
            IMPORTANCE_RANK.get(str(row.get("importance") or "medium").lower(), 1),
        )
    )
    cards = []
    for claim in claims[:CORE_CLAIM_MAX]:
        links = _rows(store, "list_links", claim_id=claim.get("claim_id")) if claim.get("claim_id") else []
        current_vid = claim.get("current_version_id")
        if current_vid and any(link.get("claim_version_id") == current_vid for link in links):
            links = [link for link in links if link.get("claim_version_id") == current_vid]
        cards.append(
            {
                "claim_id": claim.get("claim_id"),
                "claim_key": claim.get("claim_key"),
                "title": claim.get("title"),
                "statement": compact_text(claim.get("statement") or "", CLAIM_STATEMENT_WIDTH),
                "status": claim.get("final_status") or claim.get("status"),
                "confidence": claim.get("confidence"),
                "importance": claim.get("importance"),
                "why_it_matters": compact_text(claim.get("why_it_matters") or "", 240) or None,
                "strongest_support": _strongest_link(links, "support", evidence),
                "strongest_counter": _strongest_link(links, "oppose", evidence),
                "what_would_invalidate": compact_text(claim.get("what_would_invalidate") or (claim.get("reasoning") or {}).get("what_would_invalidate") or "", 240) or None,
                "financial_impact_ids": list(claim.get("financial_impact_ids") or [])[:8],
                "scenario_implication": compact_text(claim.get("scenario_implication") or "", 80) or None,
                "recent_change": _claim_recent_change(store, ticker, claim, history),
            }
        )
    return cards


def _field_deltas(from_payload: dict[str, Any], to_payload: dict[str, Any], family: str) -> list[dict[str, Any]]:
    watched = WATCHED_FIELDS.get(family)
    keys = list(watched) if watched else sorted((set(from_payload) | set(to_payload)) - SKIP_KEYS)
    out = []
    for key in keys:
        if key in SKIP_KEYS:
            continue
        before = from_payload.get(key)
        after = to_payload.get(key)
        if before == after:
            continue
        out.append(
            {
                "field": key,
                "from": before,
                "to": after,
            }
        )
    return out


def _object_label(store: Any, ticker: str, family: str, object_id: str, payload: dict[str, Any]) -> str:
    name = payload.get("name") or payload.get("title") or payload.get("canonical_key")
    if name:
        return compact_text(name, 80)
    if family == "Claim" and object_id:
        claim = store.get_claim(object_id) if hasattr(store, "get_claim") else None
        if claim:
            return compact_text(claim.get("title") or claim.get("claim_id") or object_id, 80)
    if family == "Driver" and object_id and hasattr(store, "get_driver"):
        driver = store.get_driver(object_id)
        if driver:
            return compact_text(driver.get("name") or driver.get("canonical_key") or object_id, 80)
    return compact_text(object_id or family, 80)


def _what_changed(store: Any, ticker: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in history:
        family = DELTA_TYPES.get(str(row.get("object_type") or ""))
        if not family:
            continue
        from_payload = dict(row.get("from_payload") or {})
        to_payload = dict(row.get("to_payload") or {})
        deltas = _field_deltas(from_payload, to_payload, family)
        if not deltas:
            continue
        rows.append(
            {
                "history_id": row.get("history_id"),
                "family": family,
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "label": _object_label(store, ticker, family, str(row.get("object_id") or ""), to_payload or from_payload),
                "deltas": deltas,
                "reason": compact_text(row.get("reason") or "", 240) or None,
                "event_id": row.get("event_id"),
                "created_at": row.get("created_at"),
            }
        )
    rows.sort(key=lambda item: _sort_time(item, "created_at"), reverse=True)
    latest: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("family") or ""), str(row.get("object_id") or row.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return latest[:WHAT_CHANGED_LIMIT]


def _latest_event(store: Any, ticker: str) -> dict[str, Any] | None:
    events = _rows(store, "list_events", ticker)
    events.sort(key=lambda row: (_sort_time(row, "event_date", "created_at"), str(row.get("event_id") or "")), reverse=True)
    return events[0] if events else None


def _select_hypotheses(store: Any, ticker: str) -> tuple[list[dict[str, Any]], int]:
    raw = [row for row in _rows(store, "list_hypotheses", ticker) if str(row.get("status") or "") not in RETIRED_HYPOTHESIS]
    live = [row for row in raw if not _placeholder_hypothesis(row)]
    live.sort(key=_hypothesis_rank)
    return live[:HYPOTHESIS_LIMIT], len(raw)


def _dedup_expectations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        name = _norm_text(row.get("name") or row.get("subject"))
        signature = (row.get("actual"), row.get("expected"))
        skip = False
        for existing in out:
            same_print = (existing.get("actual"), existing.get("expected")) == signature
            close_name = _token_overlap(name, _norm_text(existing.get("name") or existing.get("subject"))) >= 0.55
            if same_print and close_name:
                if str(existing.get("comparison") or "") in {"", "unknown"} and str(row.get("comparison") or "") not in {"", "unknown"}:
                    out[out.index(existing)] = row
                skip = True
                break
        if not skip:
            out.append(row)
    return out


def _usable_exposure(row: dict[str, Any]) -> bool:
    mechanism = compact_text(row.get("mechanism") or row.get("reason") or "", 80)
    obj = compact_text(row.get("object_name") or "", 80)
    if not mechanism and not obj:
        return False
    lowered = mechanism.lower()
    if lowered in {"issuer-linked exposure"} or lowered.endswith("is exposed to"):
        return bool(obj) and obj.lower() not in {"", "issuer-linked exposure"}
    return True


def _coerce_expectation_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["comparison"] = coerce_expectation_comparison(item.get("actual"), item.get("expected"), item.get("comparison"))
    return item


def _select_expectations(store: Any, ticker: str) -> tuple[list[dict[str, Any]], int]:
    raw = [_coerce_expectation_row(row) for row in _rows(store, "list_expectations", ticker)]
    rows = _dedup_expectations([row for row in raw if not _placeholder_expectation(row)])
    rows.sort(key=_expectation_rank)
    return rows[:EXPECTATION_LIMIT], len(raw)


def _latest_now_chain(
    store: Any,
    ticker: str,
    *,
    expectations: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    event = _latest_event(store, ticker)
    exposures = _rows(store, "list_exposures", ticker)
    exposures = [row for row in exposures if _usable_exposure(row)]
    if event:
        matched = [row for row in exposures if row.get("event_id") == event.get("event_id")]
        exposures = matched or exposures
    attentions = [row for row in _rows(store, "list_market_attentions", ticker) if compact_text(row.get("statement") or "", 40)]
    divergences = [
        row for row in _rows(store, "list_divergences", ticker) if str(row.get("status") or "") in UNRESOLVED_DIVERGENCE
    ]
    transmission = dict((event or {}).get("transmission") or {})
    material = None
    if event is not None:
        material = str(event.get("materiality") or "") in {"material", "high"} or bool(event.get("material"))
    chain = build_now_chain(
        event=event,
        exposures=exposures[:3],
        transmission=transmission or None,
        market_attentions=attentions[:2],
        expectations=expectations[:NOW_EXPECTATION_LIMIT],
        hypotheses=hypotheses[:NOW_HYPOTHESIS_LIMIT],
        questions=questions[:QUESTION_LIMIT],
        material=material,
        divergences=divergences[:2],
    )
    chain["event_id"] = (event or {}).get("event_id")
    chain["as_of"] = (event or {}).get("event_date") or (event or {}).get("created_at")
    return chain


def _open_questions(store: Any, ticker: str, *, has_claims: bool) -> tuple[list[dict[str, Any]], int]:
    rows = [
        row
        for row in _rows(store, "list_questions", ticker)
        if str(row.get("status") or "open").lower() not in CLOSED_QUESTION
    ]
    usable = [row for row in rows if not _low_value_question(row, has_claims=has_claims)]
    usable.sort(key=_question_rank)
    return _dedup_questions(usable)[:QUESTION_LIMIT], len(rows)


def _market_view(expectations: list[dict[str, Any]], hypotheses: list[dict[str, Any]], store: Any, ticker: str) -> dict[str, Any]:
    expectation_cards = [
        {
            "expectation_id": row.get("expectation_id"),
            "name": row.get("name") or row.get("subject"),
            "actual": row.get("actual"),
            "expected": row.get("expected"),
            "comparison": row.get("comparison"),
            "trend": row.get("trend"),
            "confidence": row.get("confidence"),
            "last_material_change": row.get("last_material_change") or None,
            "reason": compact_text(row.get("reason") or "", 160) or None,
        }
        for row in expectations
    ]
    hypothesis_cards = [
        {
            "hypothesis_id": row.get("hypothesis_id"),
            "canonical_key": row.get("canonical_key"),
            "hypothesis": compact_text(row.get("hypothesis") or row.get("name") or "", 200),
            "status": row.get("status"),
            "confidence": row.get("confidence"),
            "kind": row.get("kind"),
            "reason": compact_text(row.get("reason") or "", 160) or None,
        }
        for row in hypotheses
    ]
    unresolved = [
        {
            "divergence_id": row.get("divergence_id"),
            "status": row.get("status"),
            "explanation_grade": row.get("explanation_grade"),
            "direction": row.get("direction"),
            "price_change_pct": row.get("price_change_pct"),
            "peer_pattern": row.get("peer_pattern"),
            "unresolved_question": compact_text(row.get("unresolved_question") or "", 200) or None,
            "reason": compact_text(row.get("reason") or "", 160) or None,
            "as_of": row.get("as_of") or row.get("opened_as_of"),
        }
        for row in _rows(store, "list_divergences", ticker)
        if str(row.get("status") or "") in UNRESOLVED_DIVERGENCE
    ][:2]
    return {
        "expectations": expectation_cards,
        "active_hypotheses": hypothesis_cards,
        "price_divergence": {
            "unresolved": unresolved,
            "latest": unresolved[0] if unresolved else None,
        },
    }


def _question_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for row in rows:
        question = compact_text(row.get("question") or "", 240)
        if not question:
            continue
        cards.append(
            {
                "question_id": row.get("question_id"),
                "question": question,
                "why_it_matters": compact_text(row.get("why_it_matters") or "", 200) or None,
                "priority": row.get("priority") or "medium",
                "status": row.get("status") or "open",
                "related_claim_id": row.get("related_claim_id"),
                "related_objects": list(row.get("related_objects") or [])[:6],
            }
        )
    return cards


def pm_questions_answerable(snapshot: dict[str, Any]) -> dict[str, bool]:
    """Whether one page can answer the four PM questions from persisted data."""
    claims = list(snapshot.get("core_claims") or [])
    market = snapshot.get("market_view") or {}
    now = ((snapshot.get("now_chain") or {}).get("answers") or {})
    market_text = compact_text(now.get("what_market_is_trading") or "", 20)
    return {
        "investment_logic": bool(claims),
        "what_changed": True,
        "market": bool(
            market.get("expectations")
            or market.get("active_hypotheses")
            or (market.get("price_divergence") or {}).get("unresolved")
            or market_text
        ),
        "next_verify": bool(snapshot.get("open_research_questions")),
    }


def build_pm_view(store: Any, ticker: str, *, research: Any | None = None) -> dict[str, Any]:
    """Assemble the Investment Snapshot from persisted Brain objects only."""
    symbol = str(ticker or "").upper()
    latest = store.latest_run(symbol) if store is not None and hasattr(store, "latest_run") else None
    header = (latest or {}).get("header") or {}
    history = _rows(store, "list_history", symbol)
    history.sort(key=lambda row: _sort_time(row, "created_at"))
    evidence = _evidence_index(store, symbol, research)
    claims = _core_claims(store, symbol, evidence, history)
    changed = _what_changed(store, symbol, history)
    questions, question_total = _open_questions(store, symbol, has_claims=bool(claims))
    question_cards = _question_cards(questions)
    hypotheses, hypothesis_total = _select_hypotheses(store, symbol)
    expectations, expectation_total = _select_expectations(store, symbol)
    now_chain = _latest_now_chain(
        store,
        symbol,
        expectations=expectations,
        hypotheses=hypotheses,
        questions=questions,
    )
    market = _market_view(expectations, hypotheses, store, symbol)
    initialized = brain_has_baseline(store, symbol) if store is not None else False
    lifecycle = brain_lifecycle(store, symbol) if store is not None else "NEW_TICKER"
    snapshot = {
        "ticker": symbol,
        "company_name": header.get("company_name") or symbol,
        "status": "ready" if initialized else ("partial" if claims or changed or question_cards else "empty"),
        "lifecycle": lifecycle,
        "brain_initialized": initialized,
        "source": "persisted_brain",
        "llm_invoked": False,
        "as_of": (latest or {}).get("completed_at") or (latest or {}).get("created_at"),
        "core_claims": claims,
        "what_changed": changed,
        "now_chain": now_chain,
        "market_view": market,
        "open_research_questions": question_cards,
        "display": {
            "questions_shown": len(question_cards),
            "questions_total": question_total,
            "hypotheses_shown": len(hypotheses),
            "hypotheses_total": hypothesis_total,
            "expectations_shown": len(expectations),
            "expectations_total": expectation_total,
            "what_changed_shown": len(changed),
        },
    }
    invest = investment_snapshot(store, symbol)
    snapshot["financial_impacts"] = invest.get("financial_impacts") or []
    snapshot["base_scenario"] = invest.get("base_scenario")
    snapshot["valuation_state"] = invest.get("valuation_state")
    snapshot["current_thesis"] = invest.get("current_thesis")
    from .product_read import attach_company_overview

    snapshot = attach_company_overview(snapshot, store, symbol, research=research)
    snapshot["can_answer"] = pm_questions_answerable(snapshot)
    return snapshot
