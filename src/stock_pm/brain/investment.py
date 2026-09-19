"""Claim → Financial Impact → Scenario → ValuationState → Thesis.

Deterministic downstream. GLM does not write these objects.
Event and Price cannot propose them; only a Slow-layer change can.
"""

from __future__ import annotations

from typing import Any

from stock_pm.research.ids import new_id
from stock_pm.research.llm_reason import compact_text

from .header import company_header
from .history import record_history
from .hysteresis import accumulate_claim_evidence
from .phase0 import evaluate_brain_changes
from .types import (
    CONFIDENCE,
    DOWNSTREAM_TRIGGERS,
    HORIZONS,
    IMPACT_DIRECTIONS,
    IMPACT_METRICS,
    MAGNITUDE_BANDS,
    PROBABILITY_BANDS,
    SCENARIO_TYPES,
    VALUATION_DIRECTIONS,
)

FORBIDDEN_VALUATION_KEYS = ("fair_value", "price_target", "target_multiple", "target_pe", "dcf")
POSITIVE_TOKENS = (
    "strong",
    "strengthen",
    "durability",
    "durable",
    "ramp",
    "demand remains",
    "resilient",
    "beat",
    "upside",
)
RISK_TOKENS = (
    "concentration",
    "customer concentration",
    "risk",
    "slow",
    "compress",
    "worsen",
    "miss",
    "dependency",
    "tail risk",
)
INVALIDATION_SKIP = {"the", "a", "an", "and", "or", "of", "to", "for", "if", "is", "in", "on"}


def _blob(*parts: Any) -> str:
    return " ".join(compact_text(part or "", 240) for part in parts).lower()


def _ids(values: Any) -> list[str]:
    out: list[str] = []
    for item in values or []:
        token = str(item or "").strip()
        if token and token not in out:
            out.append(token)
    return out


def claim_polarity(claim: dict[str, Any] | None) -> str:
    item = claim or {}
    text = _blob(
        item.get("title"),
        item.get("statement"),
        item.get("claim_subject"),
        item.get("claim_dimension"),
        item.get("why_it_matters"),
    )
    if any(token in text for token in RISK_TOKENS):
        return "risk"
    if any(token in text for token in POSITIVE_TOKENS):
        return "positive"
    status = str(item.get("status") or item.get("final_status") or "")
    if status in {"challenged", "contradicted"}:
        return "risk"
    return "uncertain"


def _direction_for(polarity: str, metric: str) -> str:
    if polarity == "positive":
        if metric in {"revenue", "EPS", "FCF", "gross_margin", "operating_margin"}:
            return "positive"
        if metric == "capex":
            return "uncertain"
        return "positive"
    if polarity == "risk":
        if metric in {"revenue", "EPS", "FCF", "gross_margin", "operating_margin"}:
            return "negative"
        return "uncertain"
    return "uncertain"


def _magnitude_for(polarity: str, metric: str) -> str:
    if polarity == "positive" and metric == "revenue":
        return "large"
    if polarity == "positive" and metric in {"EPS", "operating_margin", "gross_margin"}:
        return "medium"
    if polarity == "risk" and metric in {"revenue", "operating_margin", "EPS"}:
        return "medium"
    return "unknown"


def _horizon(claim: dict[str, Any]) -> str:
    raw = str(claim.get("time_horizon") or "medium")
    return raw if raw in HORIZONS else "medium"


def default_invalidation(claim: dict[str, Any]) -> str:
    existing = compact_text(claim.get("what_would_invalidate") or "", 240)
    if existing:
        return existing
    polarity = claim_polarity(claim)
    name = compact_text(claim.get("title") or claim.get("statement") or "the claim", 80)
    if polarity == "risk":
        return f"{name} worsens with independent customer or mix evidence."
    if polarity == "positive":
        return f"{name} fails if demand slows or a named customer cuts."
    return f"Independent evidence that {name} is no longer operative."


def normalize_financial_impact(raw: dict[str, Any], *, ticker: str) -> dict[str, Any] | None:
    metric = str(raw.get("financial_metric") or raw.get("metric") or "")
    aliases = {"eps": "EPS", "fcf": "FCF", "gm": "gross_margin", "om": "operating_margin", "margin": "operating_margin"}
    metric = aliases.get(metric.lower(), metric)
    if metric not in IMPACT_METRICS:
        return None
    direction = str(raw.get("direction") or "uncertain")
    if direction in {"up", "positive", "higher"}:
        direction = "positive"
    elif direction in {"down", "negative", "lower"}:
        direction = "negative"
    if direction not in IMPACT_DIRECTIONS:
        direction = "uncertain"
    band = str(raw.get("magnitude_band") or raw.get("magnitude") or "unknown")
    if band not in MAGNITUDE_BANDS:
        band = "unknown"
    claim_id = str(raw.get("claim_id") or (raw.get("object_id") if raw.get("object_type") in {"claim", "core_claim"} else "") or "")
    horizon = str(raw.get("time_horizon") or "medium")
    if horizon not in HORIZONS:
        horizon = "medium"
    confidence = str(raw.get("confidence") or "medium")
    if confidence not in CONFIDENCE:
        confidence = "medium"
    return {
        "impact_id": raw.get("impact_id") or new_id("bfi"),
        "ticker": str(ticker).upper(),
        "claim_id": claim_id,
        "object_type": raw.get("object_type") or ("claim" if claim_id else "driver"),
        "object_id": raw.get("object_id") or claim_id,
        "financial_metric": metric,
        "metric": metric,
        "direction": direction,
        "magnitude_band": band,
        "magnitude_range": raw.get("magnitude_range"),
        "time_horizon": horizon,
        "mechanism": compact_text(raw.get("mechanism") or "", 400),
        "confidence": confidence,
        "support_evidence_ids": _ids(raw.get("support_evidence_ids") or raw.get("evidence_ids")),
        "counter_evidence_ids": _ids(raw.get("counter_evidence_ids")),
        "evidence_ids": _ids(raw.get("support_evidence_ids") or raw.get("evidence_ids")),
        "direction_only": True,
        "reason": compact_text(raw.get("reason") or "", 240),
    }


def normalize_scenario(raw: dict[str, Any], *, ticker: str) -> dict[str, Any] | None:
    kind = str(raw.get("scenario_type") or raw.get("type") or "").lower()
    if kind not in SCENARIO_TYPES:
        return None
    band = str(raw.get("probability_band") or "unknown")
    if band not in PROBABILITY_BANDS:
        band = "unknown"
    confidence = str(raw.get("confidence") or "medium")
    if confidence not in CONFIDENCE:
        confidence = "medium"
    return {
        "scenario_id": raw.get("scenario_id") or new_id("bscn"),
        "ticker": str(ticker).upper(),
        "scenario_type": kind,
        "assumptions": [compact_text(item, 160) for item in (raw.get("assumptions") or []) if compact_text(item, 160)],
        "linked_claim_ids": _ids(raw.get("linked_claim_ids")),
        "financial_impact_ids": _ids(raw.get("financial_impact_ids")),
        "probability_band": band,
        "confidence": confidence,
        "key_upside_conditions": [compact_text(item, 160) for item in (raw.get("key_upside_conditions") or []) if compact_text(item, 160)],
        "key_downside_conditions": [compact_text(item, 160) for item in (raw.get("key_downside_conditions") or []) if compact_text(item, 160)],
        "invalidation_conditions": [compact_text(item, 160) for item in (raw.get("invalidation_conditions") or []) if compact_text(item, 160)],
        "reason": compact_text(raw.get("reason") or "", 240),
    }


def _usable_multiple(value: Any) -> float | None:
    if isinstance(value, dict):
        if str(value.get("origin") or "") == "unavailable":
            return None
        value = value.get("value")
    if value in (None, "", "unavailable"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def valuation_inputs(research: Any | None, store: Any | None, ticker: str) -> dict[str, Any]:
    """Reuse reported PE / EV/EBITDA only. Never invent a fair value."""
    symbol = str(ticker).upper()
    pack: dict[str, Any] = {}
    if research is not None:
        getter = getattr(research, "get_pack", None) or getattr(getattr(research, "store", None), "get_pack", None)
        if callable(getter):
            pack = dict(getter(symbol) or {})
    header = {}
    if store is not None and hasattr(store, "latest_run"):
        header = dict((store.latest_run(symbol) or {}).get("header") or {})
    built = company_header(pack) if pack else {}
    valuation = dict(header.get("valuation") or built.get("valuation") or {})
    supporting: dict[str, Any] = {}
    for key in ("pe_ttm", "pe_forward", "ev_ebitda", "ps", "fcf_yield"):
        number = _usable_multiple(valuation.get(key))
        if number is None:
            continue
        origin = "reported"
        if isinstance(valuation.get(key), dict):
            origin = str(valuation[key].get("origin") or "reported")
            if origin == "unavailable":
                continue
        supporting[key] = {"value": number, "origin": origin, "field": key}
    for key in FORBIDDEN_VALUATION_KEYS:
        supporting.pop(key, None)
    return {"supporting_data": supporting, "valuation_data_missing": not supporting}


def normalize_valuation_state(raw: dict[str, Any], *, ticker: str, research: Any | None = None, store: Any | None = None) -> dict[str, Any]:
    inputs = valuation_inputs(research, store, ticker)
    supporting = dict(raw.get("supporting_data") or inputs["supporting_data"])
    for key in FORBIDDEN_VALUATION_KEYS:
        supporting.pop(key, None)
    missing = bool(inputs["valuation_data_missing"] if raw.get("valuation_data_missing") is None else raw.get("valuation_data_missing"))
    if not supporting:
        missing = True
    direction = str(raw.get("valuation_direction") or "uncertain")
    if direction not in VALUATION_DIRECTIONS:
        direction = "uncertain"
    if missing:
        direction = direction if direction in VALUATION_DIRECTIONS else "uncertain"
    confidence = str(raw.get("confidence") or ("medium" if not missing else "low"))
    if confidence not in CONFIDENCE:
        confidence = "low" if missing else "medium"
    return {
        "valuation_id": raw.get("valuation_id") or new_id("bval"),
        "ticker": str(ticker).upper(),
        "valuation_context": compact_text(raw.get("valuation_context") or "", 400),
        "scenario_id": raw.get("scenario_id"),
        "valuation_direction": direction,
        "confidence": confidence,
        "valuation_data_missing": missing,
        "supporting_data": supporting,
        "reason": compact_text(raw.get("reason") or "", 240),
    }


def normalize_thesis(raw: dict[str, Any], *, ticker: str) -> dict[str, Any]:
    return {
        "thesis_id": raw.get("thesis_id") or new_id("bths"),
        "ticker": str(ticker).upper(),
        "current_thesis": compact_text(raw.get("current_thesis") or "", 600),
        "top_supporting_claim_ids": _ids(raw.get("top_supporting_claim_ids")),
        "top_risk_claim_ids": _ids(raw.get("top_risk_claim_ids")),
        "base_scenario_id": raw.get("base_scenario_id"),
        "key_upside_condition": compact_text(raw.get("key_upside_condition") or "", 240),
        "key_downside_condition": compact_text(raw.get("key_downside_condition") or "", 240),
        "what_would_change_thesis": compact_text(raw.get("what_would_change_thesis") or "", 400),
        "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCE else "medium",
        "reason": compact_text(raw.get("reason") or "", 240),
    }


def impacts_from_claim(claim: dict[str, Any], *, ticker: str) -> list[dict[str, Any]]:
    polarity = claim_polarity(claim)
    metrics = ["revenue", "EPS", "operating_margin"]
    mechanism = compact_text(
        claim.get("why_it_matters")
        or claim.get("statement")
        or "Claim transmits through the existing Driver / Claim path.",
        240,
    )
    out = []
    for metric in metrics:
        direction = _direction_for(polarity, metric)
        if polarity == "positive" and metric == "operating_margin":
            direction = "positive" if "margin" in _blob(claim.get("title"), claim.get("statement"), claim.get("why_it_matters")) else "uncertain"
        row = normalize_financial_impact(
            {
                "claim_id": claim.get("claim_id"),
                "object_type": "claim",
                "object_id": claim.get("claim_id"),
                "financial_metric": metric,
                "direction": direction,
                "magnitude_band": _magnitude_for(polarity, metric),
                "time_horizon": _horizon(claim),
                "mechanism": mechanism,
                "confidence": claim.get("confidence") or "medium",
                "support_evidence_ids": claim.get("supporting_evidence_ids") or (claim.get("reasoning") or {}).get("evidence_ids") or [],
                "counter_evidence_ids": claim.get("opposing_evidence_ids") or [],
                "reason": f"Claim {claim.get('claim_id')} → {metric}",
            },
            ticker=ticker,
        )
        if row:
            out.append(row)
    return out


def _scenario_drafts(claims: list[dict[str, Any]], impacts: list[dict[str, Any]], *, ticker: str) -> list[dict[str, Any]]:
    positives = [row for row in claims if claim_polarity(row) == "positive"]
    risks = [row for row in claims if claim_polarity(row) == "risk"]
    claim_ids = _ids(row.get("claim_id") for row in claims)
    impact_ids = _ids(row.get("impact_id") for row in impacts)
    pos_text = [compact_text(row.get("title") or row.get("statement"), 80) for row in positives]
    risk_text = [compact_text(row.get("title") or row.get("statement"), 80) for row in risks]
    demand = pos_text[0] if pos_text else "core operating claim holds"
    risk = risk_text[0] if risk_text else "named operating risk stays contained"
    invalidations = [default_invalidation(row) for row in claims[:3]]
    risk_weight = len(risks)
    pos_weight = len(positives)
    bull_band = "medium" if pos_weight >= risk_weight else "low"
    bear_band = "medium" if risk_weight else "low"
    if risk_weight and risk_weight >= pos_weight:
        bear_band = "medium"
        bull_band = "low"
    drafts = [
        {
            "scenario_type": "bull",
            "assumptions": [
                f"{demand} remains strong",
                f"{risk} declines" if risks else "customer concentration stays manageable",
                "margin stays resilient",
            ],
            "probability_band": bull_band,
            "key_upside_conditions": [f"{demand} stays durable", "concentration eases"] if risks else [f"{demand} stays durable"],
            "key_downside_conditions": [f"{risk} re-accelerates"] if risks else ["demand normalizes faster than expected"],
            "invalidation_conditions": invalidations or ["Independent evidence that the live claim is broken."],
            "reason": "Bull consumes live Core Claims and Financial Impacts.",
        },
        {
            "scenario_type": "base",
            "assumptions": [
                f"{demand} remains but normalizes",
                f"{risk} remains elevated" if risks else "concentration remains a watch item",
                "margin broadly stable",
            ],
            "probability_band": "high",
            "key_upside_conditions": [f"{demand} stays stronger than the base path"],
            "key_downside_conditions": [f"{risk} worsens"] if risks else ["demand slows"],
            "invalidation_conditions": invalidations or ["The core operating claim is invalidated."],
            "reason": "Base is the working path; one claim does not rewrite it alone.",
        },
        {
            "scenario_type": "bear",
            "assumptions": [
                f"{demand} slows" if positives else "operating support fades",
                f"{risk} worsens" if risks else "a new operating risk appears",
                "margin compresses",
            ],
            "probability_band": bear_band,
            "key_upside_conditions": ["risk evidence is reversed"],
            "key_downside_conditions": [f"{risk} becomes structural"] if risks else ["demand rolls over"],
            "invalidation_conditions": invalidations or ["The bear path is contradicted by repeated operating prints."],
            "reason": "Bear support can rise with a risk claim without flipping Thesis.",
        },
    ]
    out = []
    for raw in drafts:
        row = normalize_scenario(
            {**raw, "linked_claim_ids": claim_ids, "financial_impact_ids": impact_ids, "confidence": "medium"},
            ticker=ticker,
        )
        if row:
            out.append(row)
    return out


def _valuation_direction(claims: list[dict[str, Any]], missing: bool) -> str:
    if missing:
        return "uncertain"
    polarities = [claim_polarity(row) for row in claims]
    if polarities.count("risk") > polarities.count("positive"):
        return "compression_risk"
    if polarities.count("positive") and not polarities.count("risk"):
        return "supports_expansion"
    if polarities.count("positive") and polarities.count("risk"):
        return "neutral"
    return "uncertain"


def _thesis_text(claims: list[dict[str, Any]], scenarios: list[dict[str, Any]], valuation: dict[str, Any]) -> str:
    positives = [compact_text(row.get("title") or row.get("statement"), 80) for row in claims if claim_polarity(row) == "positive"]
    risks = [compact_text(row.get("title") or row.get("statement"), 80) for row in claims if claim_polarity(row) == "risk"]
    base = next((row for row in scenarios if row.get("scenario_type") == "base"), {})
    lead = positives[0] if positives else compact_text((claims[0] or {}).get("title") or "the live core claims", 80)
    risk = risks[0] if risks else "named downside stays a watch item"
    missing = "Valuation data is missing, so the thesis does not invent a multiple." if valuation.get("valuation_data_missing") else "Valuation uses reported multiples only."
    return compact_text(
        f"Base path: {lead} remains the working operating claim. {risk}. "
        f"{(base.get('assumptions') or ['Margin stays broadly stable'])[0]}. {missing}",
        480,
    )


def build_downstream_objects(
    *,
    ticker: str,
    claims: list[dict[str, Any]],
    research: Any | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    symbol = str(ticker).upper()
    core = [row for row in claims if row.get("is_core") or str(row.get("lifecycle") or "") == "core"]
    core = core or list(claims)
    impacts: list[dict[str, Any]] = []
    for claim in core:
        impacts.extend(impacts_from_claim(claim, ticker=symbol))
    scenarios = _scenario_drafts(core, impacts, ticker=symbol)
    inputs = valuation_inputs(research, store, symbol)
    valuation = normalize_valuation_state(
        {
            "valuation_context": "Lightweight multiple context from reported pack data only.",
            "scenario_id": next((row.get("scenario_id") for row in scenarios if row.get("scenario_type") == "base"), None),
            "valuation_direction": _valuation_direction(core, inputs["valuation_data_missing"]),
            "valuation_data_missing": inputs["valuation_data_missing"],
            "supporting_data": inputs["supporting_data"],
            "reason": "Downstream valuation does not invent a fair value or price target.",
        },
        ticker=symbol,
        research=research,
        store=store,
    )
    positives = [row for row in core if claim_polarity(row) == "positive"]
    risks = [row for row in core if claim_polarity(row) == "risk"]
    base = next((row for row in scenarios if row.get("scenario_type") == "base"), {})
    bull = next((row for row in scenarios if row.get("scenario_type") == "bull"), {})
    bear = next((row for row in scenarios if row.get("scenario_type") == "bear"), {})
    thesis = normalize_thesis(
        {
            "current_thesis": _thesis_text(core, scenarios, valuation),
            "top_supporting_claim_ids": _ids(row.get("claim_id") for row in positives[:3]),
            "top_risk_claim_ids": _ids(row.get("claim_id") for row in risks[:3]),
            "base_scenario_id": base.get("scenario_id"),
            "key_upside_condition": ((bull.get("key_upside_conditions") or base.get("key_upside_conditions") or [""])[0]),
            "key_downside_condition": ((bear.get("key_downside_conditions") or base.get("key_downside_conditions") or [""])[0]),
            "what_would_change_thesis": "; ".join(base.get("invalidation_conditions") or []) or "Repeated independent evidence against the live Core Claims.",
            "confidence": "medium" if core else "low",
            "reason": "Thesis consumes Claims, Impacts, Scenarios, and ValuationState only.",
        },
        ticker=symbol,
    )
    return {"impacts": impacts, "scenarios": scenarios, "valuation": valuation, "thesis": thesis}


def _proposal(object_type: str, payload: dict[str, Any], *, ticker: str, prior: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    oid = (
        payload.get("impact_id")
        or payload.get("scenario_id")
        or payload.get("valuation_id")
        or payload.get("thesis_id")
        or payload.get("object_id")
        or ""
    )
    return {
        "object_type": object_type,
        "object_id": oid,
        "source_kind": "downstream",
        "confidence": payload.get("confidence") or "medium",
        "from_payload": dict(prior or {}),
        "to_payload": dict(payload),
        "reason": reason,
        "evidence_ids": payload.get("support_evidence_ids") or payload.get("evidence_ids") or [],
    }


def should_run_downstream(
    *,
    trigger: str | None,
    price_only: bool,
    is_full_review: bool,
    gate_result: dict[str, Any] | None = None,
    affected: dict[str, Any] | None = None,
    invalidation_hit: bool = False,
) -> bool:
    if price_only:
        return False
    token = str(trigger or "").lower()
    if token in {"thesis_refresh", "manual_thesis_refresh"}:
        return True
    if is_full_review or token == "full_review":
        return True
    gate = gate_result or {}
    approved = list(gate.get("approved") or [])
    claim_change = any(str(row.get("object_type") or "") in {"claim", "core_claim"} for row in approved) or gate.get("core_claims_unchanged") is False
    driver_change = any(str(row.get("object_type") or "") in {"driver", "value_driver"} for row in approved)
    affected_claims = bool((affected or {}).get("claims"))
    if claim_change or invalidation_hit:
        return True
    if driver_change and affected_claims:
        return True
    return token in DOWNSTREAM_TRIGGERS


def evidence_hits_invalidation(claim: dict[str, Any] | None, evidence: dict[str, Any] | None) -> bool:
    condition = compact_text((claim or {}).get("what_would_invalidate") or "", 240).lower()
    if not condition:
        return False
    hay = _blob(
        (evidence or {}).get("fact"),
        (evidence or {}).get("title"),
        (evidence or {}).get("statement"),
        (evidence or {}).get("excerpt"),
    )
    needles = [token for token in condition.replace("/", " ").replace(",", " ").split() if len(token) > 3 and token not in INVALIDATION_SKIP]
    if not needles:
        return False
    hits = sum(1 for token in needles if token in hay)
    return hits >= max(2, min(3, len(needles) // 3 or 2))


def apply_invalidation_evidence(
    store: Any,
    ticker: str,
    *,
    event: dict[str, Any] | None,
    claims: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Update support/counter momentum. Never delete the claim."""
    if store is None or str((event or {}).get("kind") or "") == "price":
        return []
    hits: list[dict[str, Any]] = []
    evidence = {
        "id": (event or {}).get("evidence_id") or (event or {}).get("id"),
        "fact": (event or {}).get("fact") or (event or {}).get("title"),
        "title": (event or {}).get("title"),
        "statement": (event or {}).get("statement"),
        "source": (event or {}).get("source"),
    }
    for claim in claims or []:
        if not evidence_hits_invalidation(claim, {**evidence, **(event or {})}):
            continue
        claim_id = str(claim.get("claim_id") or "")
        updated = accumulate_claim_evidence(claim, direction="oppose", strength="strong")
        if hasattr(store, "update_claim_pointer") and claim_id:
            current = store.get_claim(claim_id) if hasattr(store, "get_claim") else dict(claim)
            merged = dict(current or claim)
            merged["counter_strength"] = updated.get("counter_strength")
            merged["counter_trend"] = updated.get("counter_trend")
            reasoning = dict(merged.get("reasoning") or {})
            reasoning["counter_strength"] = updated.get("counter_strength")
            reasoning["support_strength"] = updated.get("support_strength") or reasoning.get("support_strength")
            merged["reasoning"] = reasoning
            store.update_claim_pointer(claim_id, merged)
        eid = str(evidence.get("id") or new_id("rev"))
        if hasattr(store, "upsert_evidence"):
            store.upsert_evidence({**evidence, "id": eid, "ticker": ticker})
        if hasattr(store, "insert_link"):
            store.insert_link(
                {
                    "claim_id": claim_id,
                    "evidence_id": eid,
                    "direction": "oppose",
                    "strength": "strong",
                    "reason": compact_text((event or {}).get("fact") or (event or {}).get("title") or "invalidation evidence", 200),
                }
            )
        record_history(
            store,
            ticker=ticker,
            object_type="core_claim",
            object_id=claim_id,
            from_payload={"counter_strength": claim.get("counter_strength") or 0, "status": claim.get("status")},
            to_payload={"counter_strength": updated.get("counter_strength"), "status": claim.get("status")},
            reason="invalidation_evidence_momentum",
        )
        hits.append({"claim_id": claim_id, "deleted": False, "status": (store.get_claim(claim_id) or claim).get("status") if hasattr(store, "get_claim") else claim.get("status")})
    return hits


def _prior_map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        token = str(row.get(key) or "")
        if token:
            out[token] = row
        if key == "metric" and row.get("claim_id"):
            out[f"{row.get('claim_id')}:{row.get('metric') or row.get('financial_metric')}"] = row
        if key == "scenario_type":
            out[str(row.get("scenario_type") or "")] = row
    return out


def run_downstream_reasoning(
    store: Any,
    ticker: str,
    *,
    trigger: str = "thesis_refresh",
    affected_claim_ids: list[str] | None = None,
    research: Any | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Thin Slow-layer pass. No GLM. Writes only through Change Proposal."""
    symbol = str(ticker).upper()
    if store is None:
        return {"ran": False, "reason": "no_store", "approved": [], "rejected": []}
    live_claims = list(claims or [])
    if not live_claims and hasattr(store, "list_active_claims"):
        live_claims = [row for row in store.list_active_claims(symbol) if row.get("is_core")]
    if affected_claim_ids:
        wanted = {str(item) for item in affected_claim_ids}
        scoped = [row for row in live_claims if str(row.get("claim_id") or "") in wanted]
        live_claims = scoped or live_claims
    if not live_claims:
        return {"ran": False, "reason": "no_core_claims", "approved": [], "rejected": []}
    for claim in live_claims:
        if not compact_text(claim.get("what_would_invalidate") or "", 8):
            claim["what_would_invalidate"] = default_invalidation(claim)
            if hasattr(store, "update_claim_pointer") and claim.get("claim_id"):
                store.update_claim_pointer(str(claim["claim_id"]), {"what_would_invalidate": claim["what_would_invalidate"]})
    built = build_downstream_objects(ticker=symbol, claims=live_claims, research=research, store=store)
    existing_impacts = store.list_financial_impacts(symbol) if hasattr(store, "list_financial_impacts") else []
    existing_scenarios = store.list_scenarios(symbol) if hasattr(store, "list_scenarios") else []
    existing_valuation = store.latest_valuation_state(symbol) if hasattr(store, "latest_valuation_state") else None
    existing_thesis = store.latest_thesis(symbol) if hasattr(store, "latest_thesis") else None
    impact_prior = _prior_map(existing_impacts, "metric")
    scenario_prior = _prior_map(existing_scenarios, "scenario_type")
    proposals = []
    for row in built["impacts"]:
        prior = impact_prior.get(f"{row.get('claim_id')}:{row.get('metric')}") or impact_prior.get(str(row.get("metric") or ""))
        if prior:
            row["impact_id"] = prior.get("impact_id") or row["impact_id"]
        proposals.append(_proposal("financial_impact", row, ticker=symbol, prior=prior, reason="downstream_financial_impact"))
    for row in built["scenarios"]:
        prior = scenario_prior.get(str(row.get("scenario_type") or ""))
        if prior:
            row["scenario_id"] = prior.get("scenario_id") or row["scenario_id"]
        proposals.append(_proposal("scenario", row, ticker=symbol, prior=prior, reason="downstream_scenario"))
    valuation = built["valuation"]
    if existing_valuation:
        valuation["valuation_id"] = existing_valuation.get("valuation_id") or valuation["valuation_id"]
    proposals.append(_proposal("valuation_state", valuation, ticker=symbol, prior=existing_valuation, reason="downstream_valuation"))
    proposals.append(_proposal("thesis_snapshot", built["thesis"], ticker=symbol, prior=existing_thesis, reason="downstream_thesis"))
    gate = evaluate_brain_changes(
        ticker=symbol,
        proposals=proposals,
        brain={"claims": live_claims},
        store=store,
    )
    by_claim: dict[str, list[str]] = {}
    for row in built["impacts"]:
        by_claim.setdefault(str(row.get("claim_id") or ""), []).append(str(row.get("impact_id") or ""))
    base = next((row for row in built["scenarios"] if row.get("scenario_type") == "base"), {})
    bear = next((row for row in built["scenarios"] if row.get("scenario_type") == "bear"), {})
    for claim in live_claims:
        cid = str(claim.get("claim_id") or "")
        polarity = claim_polarity(claim)
        implication = "base_supported"
        if polarity == "risk":
            implication = "bear_support_up"
        elif polarity == "positive":
            implication = "bull_and_base_supported"
        if hasattr(store, "update_claim_pointer") and cid:
            store.update_claim_pointer(
                cid,
                {
                    "what_would_invalidate": claim.get("what_would_invalidate") or default_invalidation(claim),
                    "financial_impact_ids": by_claim.get(cid) or [],
                    "scenario_implication": implication,
                },
            )
    return {
        "ran": True,
        "trigger": trigger,
        "approved": gate.get("approved") or [],
        "rejected": gate.get("rejected") or [],
        "requires_review": gate.get("requires_review") or [],
        "impacts": store.list_financial_impacts(symbol) if hasattr(store, "list_financial_impacts") else built["impacts"],
        "scenarios": store.list_scenarios(symbol) if hasattr(store, "list_scenarios") else built["scenarios"],
        "valuation": (store.latest_valuation_state(symbol) if hasattr(store, "latest_valuation_state") else built["valuation"]),
        "thesis": (store.latest_thesis(symbol) if hasattr(store, "latest_thesis") else built["thesis"]),
        "base_scenario_id": base.get("scenario_id"),
        "bear_probability": (bear or {}).get("probability_band"),
        "glm_called": False,
    }


def investment_snapshot(store: Any, ticker: str) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    if store is None:
        return {"financial_impacts": [], "base_scenario": None, "valuation_state": None, "current_thesis": None}
    impacts = store.list_financial_impacts(symbol) if hasattr(store, "list_financial_impacts") else []
    scenarios = store.list_scenarios(symbol) if hasattr(store, "list_scenarios") else []
    base = next((row for row in scenarios if str(row.get("scenario_type") or "") == "base"), None)
    return {
        "financial_impacts": [
            {
                "impact_id": row.get("impact_id"),
                "claim_id": row.get("claim_id") or (row.get("object_id") if row.get("object_type") in {"claim", "core_claim"} else None),
                "financial_metric": row.get("financial_metric") or row.get("metric"),
                "direction": row.get("direction"),
                "magnitude_band": row.get("magnitude_band"),
                "time_horizon": row.get("time_horizon"),
                "mechanism": row.get("mechanism"),
                "confidence": row.get("confidence"),
            }
            for row in impacts
            if (row.get("claim_id") or row.get("object_type") in {"claim", "core_claim"})
        ],
        "scenarios": scenarios,
        "base_scenario": base,
        "valuation_state": store.latest_valuation_state(symbol) if hasattr(store, "latest_valuation_state") else None,
        "current_thesis": store.latest_thesis(symbol) if hasattr(store, "latest_thesis") else None,
    }
