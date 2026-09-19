"""PM View / Investment Snapshot.

Read-only assembly of a persisted Brain. No GLM, no research pack rebuild,
no architecture change. Answers four PM questions on one payload:

1. What is the live investment logic? (Core Claims)
2. What actually changed? (State / Driver / Expectation / Claim deltas)
3. What might the market be trading? (Expectation / hypotheses / divergence + Now Chain)
4. What must be verified next? (open research questions)
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.llm_reason import compact_text

from .bootstrap import brain_has_baseline, brain_lifecycle
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
WHAT_CHANGED_LIMIT = 16


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
    claims = [row for row in _rows(store, "list_active_claims", ticker) if row.get("is_core")]
    claims.sort(
        key=lambda row: (
            IMPORTANCE_RANK.get(str(row.get("importance") or "medium").lower(), 1),
            -len(str(row.get("updated_at") or "")),
            str(row.get("claim_id") or ""),
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
                "statement": compact_text(claim.get("statement") or "", 320),
                "status": claim.get("final_status") or claim.get("status"),
                "confidence": claim.get("confidence"),
                "importance": claim.get("importance"),
                "why_it_matters": compact_text(claim.get("why_it_matters") or "", 240) or None,
                "strongest_support": _strongest_link(links, "support", evidence),
                "strongest_counter": _strongest_link(links, "oppose", evidence),
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
    return rows[:WHAT_CHANGED_LIMIT]


def _latest_event(store: Any, ticker: str) -> dict[str, Any] | None:
    events = _rows(store, "list_events", ticker)
    events.sort(key=lambda row: (_sort_time(row, "event_date", "created_at"), str(row.get("event_id") or "")), reverse=True)
    return events[0] if events else None


def _latest_now_chain(store: Any, ticker: str) -> dict[str, Any]:
    event = _latest_event(store, ticker)
    exposures = _rows(store, "list_exposures", ticker)
    if event:
        matched = [row for row in exposures if row.get("event_id") == event.get("event_id")]
        exposures = matched or exposures
    expectations = _rows(store, "list_expectations", ticker)
    hypotheses = [
        row
        for row in _rows(store, "list_hypotheses", ticker)
        if str(row.get("status") or "") not in RETIRED_HYPOTHESIS
    ]
    divergences = _rows(store, "list_divergences", ticker)
    questions = _open_questions(store, ticker)
    attentions = _rows(store, "list_market_attentions", ticker)
    transmission = dict((event or {}).get("transmission") or {})
    material = None
    if event is not None:
        material = str(event.get("materiality") or "") in {"material", "high"} or bool(event.get("material"))
    chain = build_now_chain(
        event=event,
        exposures=exposures,
        transmission=transmission or None,
        market_attentions=attentions,
        expectations=expectations,
        hypotheses=hypotheses,
        questions=questions,
        material=material,
        divergences=divergences,
    )
    chain["event_id"] = (event or {}).get("event_id")
    chain["as_of"] = (event or {}).get("event_date") or (event or {}).get("created_at")
    return chain


def _open_questions(store: Any, ticker: str) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _rows(store, "list_questions", ticker)
        if str(row.get("status") or "open").lower() not in CLOSED_QUESTION
    ]
    rows.sort(
        key=lambda row: (
            PRIORITY_RANK.get(str(row.get("priority") or "medium").lower(), 1),
            _sort_time(row, "created_at"),
        )
    )
    return rows


def _market_view(store: Any, ticker: str) -> dict[str, Any]:
    expectations = []
    for row in _rows(store, "list_expectations", ticker):
        expectations.append(
            {
                "expectation_id": row.get("expectation_id"),
                "name": row.get("name") or row.get("subject"),
                "actual": row.get("actual"),
                "expected": row.get("expected"),
                "comparison": row.get("comparison"),
                "trend": row.get("trend"),
                "confidence": row.get("confidence"),
                "last_material_change": row.get("last_material_change") or None,
                "reason": compact_text(row.get("reason") or "", 200) or None,
            }
        )
    expectations.sort(key=lambda row: str(row.get("last_material_change") or ""), reverse=True)
    hypotheses = []
    for row in _rows(store, "list_hypotheses", ticker):
        if str(row.get("status") or "") in RETIRED_HYPOTHESIS:
            continue
        hypotheses.append(
            {
                "hypothesis_id": row.get("hypothesis_id"),
                "canonical_key": row.get("canonical_key"),
                "hypothesis": compact_text(row.get("hypothesis") or row.get("name") or "", 240),
                "status": row.get("status"),
                "confidence": row.get("confidence"),
                "kind": row.get("kind"),
                "reason": compact_text(row.get("reason") or "", 200) or None,
            }
        )
    divergences = _rows(store, "list_divergences", ticker)
    unresolved = [
        {
            "divergence_id": row.get("divergence_id"),
            "status": row.get("status"),
            "explanation_grade": row.get("explanation_grade"),
            "direction": row.get("direction"),
            "price_change_pct": row.get("price_change_pct"),
            "peer_pattern": row.get("peer_pattern"),
            "unresolved_question": compact_text(row.get("unresolved_question") or "", 240) or None,
            "reason": compact_text(row.get("reason") or "", 200) or None,
            "as_of": row.get("as_of") or row.get("opened_as_of"),
        }
        for row in divergences
        if str(row.get("status") or "") in UNRESOLVED_DIVERGENCE
    ]
    return {
        "expectations": expectations,
        "active_hypotheses": hypotheses,
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
    now_chain = _latest_now_chain(store, symbol)
    market = _market_view(store, symbol)
    questions = _question_cards(_open_questions(store, symbol))
    initialized = brain_has_baseline(store, symbol) if store is not None else False
    lifecycle = brain_lifecycle(store, symbol) if store is not None else "NEW_TICKER"
    snapshot = {
        "ticker": symbol,
        "company_name": header.get("company_name") or symbol,
        "status": "ready" if initialized else ("partial" if claims or changed or questions else "empty"),
        "lifecycle": lifecycle,
        "brain_initialized": initialized,
        "source": "persisted_brain",
        "llm_invoked": False,
        "as_of": (latest or {}).get("completed_at") or (latest or {}).get("created_at"),
        "core_claims": claims,
        "what_changed": changed,
        "now_chain": now_chain,
        "market_view": market,
        "open_research_questions": questions,
    }
    snapshot["can_answer"] = pm_questions_answerable(snapshot)
    return snapshot
