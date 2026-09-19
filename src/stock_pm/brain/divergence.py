"""PriceFundamentalDivergence: price is a sensor, not fundamental evidence.

Price may update Market Attention, Expectation, Market Driver Hypothesis,
and Research Questions. It cannot write Fundamental State, Core Claim,
or an established causal edge.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .hypothesis import peer_pattern
from .types import BRAIN_GAP_KINDS, DIVERGENCE_STATUSES, EXPLANATION_GRADES

UNRESOLVED_PRICE_QUESTION = "What is the market pricing that the current Brain does not explain?"
_FUNDAMENTAL_EVENT_TYPES = {
    "earnings",
    "guidance",
    "customer",
    "demand",
    "capex",
    "competition",
    "mna",
    "regulation",
    "supply",
}
_EXPLAIN_NEEDLES = (
    "guidance",
    "earnings",
    "cut",
    "lowered",
    "reduced",
    "miss",
    "beat",
    "demand weakness",
    "customer",
    "confirm",
    "order",
    "capex",
)
_PRICE_EVIDENCE_PREFIXES = ("price:", "price_obs", "price_move", "price_change")


def _blob(event: dict[str, Any] | None) -> str:
    item = event or {}
    return f"{item.get('title') or ''} {item.get('fact') or ''} {item.get('statement') or ''}".lower()


def _tape(event: dict[str, Any] | None) -> float | None:
    try:
        return float((event or {}).get("price_change_pct"))
    except (TypeError, ValueError):
        return None


def _as_of(event: dict[str, Any] | None) -> str:
    item = event or {}
    return str(item.get("as_of") or item.get("observed_at") or item.get("date") or item.get("event_key") or "")


def _event_id(event: dict[str, Any] | None) -> str:
    item = event or {}
    return str(item.get("event_id") or item.get("event_key") or item.get("title") or "")


def _confirmed_news(event: dict[str, Any] | None) -> bool:
    item = event or {}
    if str(item.get("kind") or "") == "price":
        return False
    if str(item.get("fact_reliability") or "") in {"rumor", "signal", "opinion"}:
        return False
    if str(item.get("kind") or "") == "rumor":
        return False
    if item.get("confirmed") is False:
        return False
    return str(item.get("fact_reliability") or "") == "direct_fact" or bool(item.get("confirmed"))


def _signatures(rows: list[dict[str, Any]] | None, *keys: str) -> tuple[tuple[str, ...], ...]:
    out: list[tuple[str, ...]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ident = str(row.get(keys[0]) or row.get("name") or row.get("canonical_key") or "")
        if not ident:
            continue
        out.append(tuple(str(row.get(key) or "") for key in keys))
    return tuple(sorted(out))


def looks_like_price_evidence(token: str | None) -> bool:
    low = str(token or "").strip().lower()
    if not low:
        return False
    return any(low.startswith(prefix) for prefix in _PRICE_EVIDENCE_PREFIXES) or "price_change" in low


def price_as_evidence_forbidden(
    evidence_ids: list[str] | None,
    *,
    price_observation_ids: list[str] | None = None,
) -> bool:
    """True when a write tries to treat a price observation as fundamental evidence."""
    banned = {str(item).strip().lower() for item in (price_observation_ids or []) if str(item).strip()}
    for token in evidence_ids or []:
        raw = str(token or "").strip()
        if not raw:
            continue
        if looks_like_price_evidence(raw) or raw.lower() in banned:
            return True
    return False


def strip_price_evidence(
    evidence_ids: list[str] | None,
    *,
    price_observation_ids: list[str] | None = None,
) -> list[str]:
    banned = {str(item).strip().lower() for item in (price_observation_ids or []) if str(item).strip()}
    kept: list[str] = []
    for token in evidence_ids or []:
        raw = str(token or "").strip()
        if not raw:
            continue
        if looks_like_price_evidence(raw) or raw.lower() in banned:
            continue
        kept.append(raw)
    return list(dict.fromkeys(kept))


def divergence_signature(event: dict[str, Any] | None, *, company_specific: bool) -> str:
    move = _tape(event)
    direction = "down" if (move or 0) < 0 else "up"
    if company_specific:
        return f"company_specific_unexplained_{direction}"
    return f"unexplained_{direction}"


def normalize_divergence(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or raw.get("ticker") or "").upper()
    status = str(raw.get("status") or "open")
    if status not in DIVERGENCE_STATUSES:
        status = "open"
    grade = str(raw.get("explanation_grade") or raw.get("grade") or "largely_unexplained")
    if grade not in EXPLANATION_GRADES:
        grade = "largely_unexplained"
    signature = compact_text(raw.get("signature") or "unexplained_down", 80) or "unexplained_down"
    question = compact_text(raw.get("unresolved_question") or UNRESOLVED_PRICE_QUESTION, 240)
    return {
        "divergence_id": raw.get("divergence_id") or new_id("bpfd"),
        "ticker": symbol,
        "signature": signature,
        "kind": "price_fundamental_divergence",
        "status": status,
        "explanation_grade": grade,
        "direction": str(raw.get("direction") or ("down" if "down" in signature else "up")),
        "price_change_pct": raw.get("price_change_pct"),
        "peer_pattern": raw.get("peer_pattern"),
        "opened_by_event_id": raw.get("opened_by_event_id"),
        "opened_as_of": raw.get("opened_as_of") or "",
        "resolved_by_event_id": raw.get("resolved_by_event_id"),
        "resolved_as_of": raw.get("resolved_as_of") or "",
        "known_at_open": dict(raw.get("known_at_open") or {}),
        "resolution_evidence_ids": strip_price_evidence(
            [str(item) for item in (raw.get("resolution_evidence_ids") or []) if str(item).strip()],
            price_observation_ids=[str(item) for item in (raw.get("price_observation_ids") or []) if str(item).strip()],
        ),
        "price_observation_ids": [str(item) for item in (raw.get("price_observation_ids") or []) if str(item).strip()][:12],
        "price_is_not_evidence_for_resolution": True,
        "unresolved_question": question,
        "reason": compact_text(
            raw.get("reason") or "Current Brain cannot fully explain current price behavior.",
            240,
        ),
        "source_kind": str(raw.get("source_kind") or "price"),
        "observation_count": int(raw.get("observation_count") or 1),
        "as_of": raw.get("as_of") or raw.get("opened_as_of") or "",
    }


def explain_price_move(
    event: dict[str, Any] | None,
    *,
    ticker: str,
    prior_states: list[dict[str, Any]] | None = None,
    current_states: list[dict[str, Any]] | None = None,
    prior_claims: list[dict[str, Any]] | None = None,
    current_claims: list[dict[str, Any]] | None = None,
    expectation: dict[str, Any] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    financial_changed: bool | None = None,
) -> dict[str, Any]:
    """Grade whether the current Brain can explain a material price move.

    Does not invent precise percent attribution.
    """
    item = event or {}
    move = _tape(item)
    peers = item.get("peers") or item.get("peer_moves") or {}
    pattern = peer_pattern(move, peers if isinstance(peers, dict) else None)
    try:
        tape_abs = abs(float(move)) if move is not None else 0.0
    except (TypeError, ValueError):
        tape_abs = 0.0
    relative = 0.0
    if isinstance(peers, dict) and move is not None:
        values: list[float] = []
        for value in peers.values():
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if values:
            relative = abs(float(move) - (sum(values) / len(values)))
    abnormal = tape_abs >= 5 or relative >= 4
    material = abnormal or move is not None and tape_abs >= 5
    if prior_states is not None and current_states is not None and prior_states is not current_states:
        fund_changed = _signatures(prior_states, "state_id", "statement") != _signatures(
            current_states, "state_id", "statement"
        )
    else:
        fund_changed = bool(item.get("fundamental_state_changed"))
    if prior_claims is not None and current_claims is not None and prior_claims is not current_claims:
        claim_changed = _signatures(prior_claims, "claim_id", "statement", "status") != _signatures(
            current_claims, "claim_id", "statement", "status"
        )
    else:
        claim_changed = bool(item.get("core_claim_changed"))
    comparison = str((expectation or {}).get("comparison") or "")
    trend = str((expectation or {}).get("trend") or "")
    expectation_changed = comparison in {"above", "below"} or trend in {"rising", "falling"}
    blob = _blob(item)
    event_type = str(item.get("event_type") or "").lower()
    known_event = _confirmed_news(item) and (
        event_type in _FUNDAMENTAL_EVENT_TYPES or any(token in blob for token in _EXPLAIN_NEEDLES)
    )
    if str(item.get("kind") or "") == "price":
        known_event = False
    finance_changed = bool(financial_changed)
    if known_event and event_type in {"guidance", "earnings"}:
        finance_changed = True
    live_hyps = [row for row in (hypotheses or []) if str(row.get("status") or "") not in {"retired", "closed"}]
    news_hyp_explains = any(
        str(row.get("status") or "") in {"supported", "open"}
        and str(row.get("kind") or "") not in {"company_specific", "other"}
        and str(row.get("source_kind") or "") != "price"
        for row in live_hyps
    )
    sector_explains = pattern == "sector_macro"
    company_specific = pattern == "company_specific"
    market_hyp_explains = news_hyp_explains or sector_explains
    checks = {
        "fundamental_state_changed": bool(fund_changed),
        "core_claim_changed": bool(claim_changed),
        "expectation_changed": bool(expectation_changed),
        "known_event_explains": bool(known_event),
        "market_hypothesis_explains": bool(market_hyp_explains),
        "peer_sector_explains": bool(sector_explains),
        "financial_trajectory_changed": bool(finance_changed),
        "company_specific": bool(company_specific),
    }
    sources = [name for name, hit in checks.items() if hit and name != "company_specific"]
    grade: str | None = None
    if not material and known_event:
        grade = "well_explained"
    elif not material:
        grade = None
    elif known_event or fund_changed or claim_changed:
        grade = "well_explained"
    elif sector_explains:
        grade = "well_explained"
    elif expectation_changed or news_hyp_explains:
        grade = "partially_explained"
    else:
        grade = "largely_unexplained"
    should_create = bool(material and grade == "largely_unexplained")
    if grade == "well_explained":
        feedback = "current Brain explains the move"
    elif grade == "partially_explained":
        feedback = "current Brain explains only part of the move"
    elif grade == "largely_unexplained":
        feedback = "current Brain cannot explain the move"
    else:
        feedback = "no material price move to explain"
    known_at = {
        "as_of": _as_of(item),
        "fundamental_state_changed": bool(fund_changed),
        "core_claim_changed": bool(claim_changed),
        "expectation_changed": bool(expectation_changed),
        "known_event_explains": bool(known_event),
        "peer_pattern": pattern,
        "event_id": _event_id(item),
    }
    return {
        "ticker": str(ticker).upper(),
        "material": bool(material),
        "abnormal": bool(abnormal),
        "tape_move": move,
        "peer_pattern": pattern,
        "checks": checks,
        "explanation_sources": sources,
        "grade": grade,
        "company_specific": bool(company_specific),
        "should_create_divergence": should_create,
        "feedback": feedback,
        "signature": divergence_signature(item, company_specific=company_specific),
        "known_at": known_at,
        "unresolved_question": UNRESOLVED_PRICE_QUESTION if should_create else None,
    }


def _match_open(existing: list[dict[str, Any]] | None, *, ticker: str, signature: str) -> dict[str, Any] | None:
    symbol = str(ticker).upper()
    for row in existing or []:
        if str(row.get("ticker") or "").upper() != symbol:
            continue
        if str(row.get("signature") or "") != signature:
            continue
        if str(row.get("status") or "") in {"open", "partially_explained"}:
            return dict(row)
    return None


def apply_divergence_lifecycle(
    explanation: dict[str, Any] | None,
    *,
    ticker: str,
    event: dict[str, Any] | None,
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Open, partially explain, or resolve a divergence. Never rewrite what was known at open."""
    item = event or {}
    explained = dict(explanation or {})
    symbol = str(ticker).upper()
    signature = str(explained.get("signature") or divergence_signature(item, company_specific=bool(explained.get("company_specific"))))
    matched = _match_open(existing, ticker=symbol, signature=signature)
    if matched is None:
        for row in existing or []:
            if str(row.get("ticker") or "").upper() != symbol:
                continue
            if str(row.get("status") or "") in {"open", "partially_explained"}:
                matched = dict(row)
                break
    grade = explained.get("grade")
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    event_id = _event_id(item)
    as_of = _as_of(item)
    price_ids = [event_id] if str(item.get("kind") or "") == "price" or explained.get("should_create_divergence") else []
    if explained.get("should_create_divergence"):
        if matched:
            nxt = normalize_divergence(
                {
                    **matched,
                    "observation_count": int(matched.get("observation_count") or 1) + 1,
                    "price_change_pct": item.get("price_change_pct", matched.get("price_change_pct")),
                    "peer_pattern": explained.get("peer_pattern") or matched.get("peer_pattern"),
                    "price_observation_ids": list(
                        dict.fromkeys(list(matched.get("price_observation_ids") or []) + price_ids)
                    ),
                    "status": "open",
                    "explanation_grade": "largely_unexplained",
                    "as_of": as_of or matched.get("as_of"),
                },
                ticker=symbol,
            )
            updated.append(nxt)
        else:
            nxt = normalize_divergence(
                {
                    "signature": signature,
                    "status": "open",
                    "explanation_grade": "largely_unexplained",
                    "direction": "down" if (explained.get("tape_move") or 0) < 0 else "up",
                    "price_change_pct": item.get("price_change_pct"),
                    "peer_pattern": explained.get("peer_pattern"),
                    "opened_by_event_id": event_id,
                    "opened_as_of": as_of,
                    "known_at_open": explained.get("known_at") or {},
                    "price_observation_ids": price_ids,
                    "unresolved_question": UNRESOLVED_PRICE_QUESTION,
                    "reason": "Current Brain cannot fully explain current price behavior.",
                    "source_kind": "price",
                    "as_of": as_of,
                },
                ticker=symbol,
            )
            created.append(nxt)
        live = (updated or created)[0]
        proposals.append(
            {
                "object_type": "price_fundamental_divergence",
                "object_id": live.get("divergence_id"),
                "source_kind": "price",
                "to": live,
                "from": matched or {},
                "reason": live.get("reason"),
            }
        )
        proposals.append(
            {
                "object_type": "market_attention",
                "source_kind": "price",
                "to": {
                    "name": "unexplained_price_vs_brain",
                    "statement": "Price behavior is not fully explained by the current Brain.",
                    "alignment": "unexplained",
                    "related_objects": [symbol],
                },
                "reason": "Unexplained tape is a market attention signal, not a fundamental rewrite.",
            }
        )
        questions.append(
            {
                "question": UNRESOLVED_PRICE_QUESTION,
                "reason": "Unresolved price divergence.",
                "related_objects": [symbol, live.get("divergence_id") or ""],
            }
        )
        proposals.append(
            {
                "object_type": "research_question",
                "source_kind": "price",
                "to": {"question": UNRESOLVED_PRICE_QUESTION, "kind": "price_feedback"},
                "reason": "Price move is unresolved. Research first; do not rewrite Claim.",
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
    elif matched and grade in {"well_explained", "partially_explained"}:
        resolution_ids = []
        if _confirmed_news(item):
            resolution_ids.append(event_id)
        nxt_status = "resolved" if grade == "well_explained" else "partially_explained"
        nxt = normalize_divergence(
            {
                **matched,
                "status": nxt_status,
                "explanation_grade": grade,
                "resolved_by_event_id": event_id if nxt_status == "resolved" else matched.get("resolved_by_event_id"),
                "resolved_as_of": as_of if nxt_status == "resolved" else matched.get("resolved_as_of"),
                "known_at_open": dict(matched.get("known_at_open") or {}),
                "resolution_evidence_ids": strip_price_evidence(
                    list(matched.get("resolution_evidence_ids") or []) + resolution_ids,
                    price_observation_ids=list(matched.get("price_observation_ids") or []) + price_ids,
                ),
                "price_is_not_evidence_for_resolution": True,
                "as_of": as_of or matched.get("as_of"),
            },
            ticker=symbol,
        )
        updated.append(nxt)
        proposals.append(
            {
                "object_type": "price_fundamental_divergence",
                "object_id": nxt.get("divergence_id"),
                "source_kind": item.get("kind") or "news",
                "to": nxt,
                "from": matched,
                "reason": "Later evidence can explain an earlier unexplained tape without rewriting what was known then.",
                "evidence_ids": nxt.get("resolution_evidence_ids") or [],
            }
        )
    live_rows = created + updated
    still_open = [row for row in live_rows if str(row.get("status") or "") == "open"]
    if not still_open and matched is None:
        for row in existing or []:
            if str(row.get("ticker") or "").upper() == symbol and str(row.get("status") or "") == "open":
                still_open.append(row)
    return {
        "proposals": proposals,
        "questions": questions,
        "created": created,
        "updated": updated,
        "resolved": [row for row in updated if str(row.get("status") or "") == "resolved"],
        "partially_explained": [row for row in updated if str(row.get("status") or "") == "partially_explained"],
        "still_open": still_open,
        "expired": [row for row in updated if str(row.get("status") or "") == "expired"],
        "hindsight_contamination": 0,
    }


def repeated_divergence_gaps(
    divergences: list[dict[str, Any]] | None,
    *,
    ticker: str,
) -> dict[str, Any]:
    """Repeated unexplained tape → Brain Gap research questions only. Never an established edge."""
    symbol = str(ticker).upper()
    rows = [
        row
        for row in (divergences or [])
        if str(row.get("ticker") or "").upper() == symbol
        and str(row.get("status") or "") in {"open", "partially_explained", "expired", "resolved"}
    ]
    by_sig: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("signature") or "unexplained")
        by_sig.setdefault(key, []).append(row)
        if int(row.get("observation_count") or 1) >= 2:
            by_sig.setdefault(f"{key}::repeat", []).append(row)
    patterns = [key for key, items in by_sig.items() if len(items) >= 2 or key.endswith("::repeat")]
    if not patterns and any(int(row.get("observation_count") or 1) >= 2 for row in rows):
        patterns = [str(rows[0].get("signature") or "unexplained")]
    if not patterns and len(rows) >= 2:
        patterns = [str(rows[0].get("signature") or "unexplained")]
    questions: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    if not patterns:
        return {"patterns": [], "questions": [], "proposals": [], "gaps": []}
    labels = {
        "missing_market_driver": f"Is there a missing Market Driver that would explain repeated unexplained {symbol} tape?",
        "missing_expectation_variable": f"Is a missing Expectation variable leaving repeated unexplained {symbol} tape?",
        "missing_exposure": f"Is a missing Exposure leaving repeated unexplained {symbol} price behavior?",
        "missing_causal_edge": f"Is a missing Causal Edge leaving repeated unexplained {symbol} tape?",
    }
    gaps: list[dict[str, Any]] = []
    for kind in BRAIN_GAP_KINDS:
        question = labels[kind]
        gaps.append({"kind": kind, "status": "proposal", "question": question})
        questions.append({"question": question, "reason": "Repeated unexplained divergence.", "related_objects": [symbol, kind]})
        proposals.append(
            {
                "object_type": "research_question",
                "source_kind": "price",
                "to": {"question": question, "kind": "brain_gap", "gap_kind": kind, "status": "proposal"},
                "reason": "Repeated unexplained price divergence. Proposal only; do not establish a causal edge.",
            }
        )
    return {"patterns": patterns, "questions": questions, "proposals": proposals, "gaps": gaps}
