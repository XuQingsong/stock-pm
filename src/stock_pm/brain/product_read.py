"""V1 Step 1: thin read-side mapping over the existing Brain kernel.

Does not persist a second MarketDominantDriver / Sensitivity store.
Assembles page payloads from Company State, Value Driver, Core Claim,
Evidence, Expectation, Market Driver Hypothesis, Market Attention,
PriceFundamentalDivergence, Event, Exposure, Causal Edge, Financial Impact,
Scenario, Valuation State, ThesisSnapshot, History.

Page paths never invoke GLM.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from stock_pm.research.llm_reason import compact_text

from .investment import investment_snapshot
from .types import CORE_CLAIM_MAX, FUNDAMENTAL_CLAIM_TYPES

RETIRED_HYPOTHESIS = {"retired", "rejected", "closed"}
UNRESOLVED_DIVERGENCE = {"open", "partially_explained"}
PLACEHOLDER_HYP_KEYS = {"other", "unresolved"}
PLACEHOLDER_HYP_TEXT = {
    "other",
    "market driver is unresolved",
    "company-specific concern",
    "sector / macro move",
    "sector wide semiconductor selloff",
}

EMPTY_DOMINANT = "当前尚未形成明确主导变量"
PRICE_EXPLAINED = "基本能够解释"
PRICE_PARTIAL = "部分能够解释"
PRICE_UNEXPLAINED = "目前难以充分解释"
PRICE_NOT_ASSESSED = "尚无价格归因证据"

MARKET_WIDE_KINDS = {"ai_demand", "sector_macro"}
MARKET_WIDE_KEYS = {
    "ai_demand": "ai_capex_expectations",
    "ai_capex_expectations": "ai_capex_expectations",
    "sector_macro": "sector_macro",
    "real_yields": "real_yields",
    "rates": "real_yields",
}

THEME_NEEDLES = (
    ("ai_capex_expectations", ("ai demand", "ai capex", "capital expenditure", "hyperscaler", "custom silicon", "asic", "xpu", "ai 资本", "资本开支")),
    ("real_yields", ("real yield", "treasury", "rates", "利率", "美债", "yield")),
    ("sector_macro", ("sector", "macro", "sox", "semiconductor cycle", "板块")),
)

ISSUER_ACTION = re.compile(
    r"\b(meta|facebook|google|alphabet|microsoft|amazon|nvidia|apple|broadcom|lumentum|oracle|tesla)\b"
    r".{0,48}\b(capex|capital expenditure|opex|guidance|raises|cuts|boosts|hikes|increases|提高|上调|下调)\b"
    "|"
    r"\b(raises|cuts|boosts|hikes|increases|提高|上调)\b.{0,32}"
    r"\b(capex|capital expenditure|opex|guidance)\b.{0,24}"
    r"\b(meta|facebook|google|alphabet|microsoft|amazon|nvidia)\b",
    re.I,
)
MARKET_PRICING_CLAIM = re.compile(
    r"市场在交易|market is trading|market is pricing|市场在定价|"
    r"估值对.{0,12}敏感|valuation (is )?sensitive to|"
    r"rate[- ]sensitive|multiple compression is the|"
    r"the premium multiple\b|估值倍数",
    re.I,
)
EVENT_NODE_TYPES = {"event", "observation", "news", "price", "signal"}
TRIGGER_EVENT_TYPES = {"capex", "guidance", "earnings", "product", "customer"}
ROLE_LABELS = ("主导", "次主导", "辅助")
THEME_DISPLAY_ZH = {
    "ai_capex_expectations": "AI 资本开支",
    "real_yields": "美债收益率",
    "sector_macro": "板块与宏观",
}
CHANGE_KIND_ZH = {
    "market_driver_hypothesis": "主轴",
    "market_attention": "主轴",
    "expectation": "主轴",
    "macro_state": "主轴",
    "industry_state": "主轴",
}


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


def _placeholder_hypothesis(row: dict[str, Any]) -> bool:
    key = str(row.get("canonical_key") or "").strip().lower()
    text = str(row.get("hypothesis") or row.get("name") or "").strip().lower()
    if key in PLACEHOLDER_HYP_KEYS or text in PLACEHOLDER_HYP_TEXT:
        return True
    return bool(key) and "_" in key and _norm_text(text) == _norm_text(key.replace("_", " "))


def _hay(row: dict[str, Any] | None, *keys: str) -> str:
    item = row or {}
    default = (
        "name",
        "title",
        "statement",
        "hypothesis",
        "canonical_key",
        "kind",
        "reason",
        "subject",
        "current_state",
        "object_name",
        "mechanism",
        "why_it_matters",
    )
    return " ".join(str(item.get(key) or "") for key in (keys or default)).lower()


def is_trigger_event(row: dict[str, Any] | None) -> bool:
    """Issuer-specific capex/guidance/print. Evidence only — never a global driver or sensitivity row."""
    item = row or {}
    if item.get("event_id") or str(item.get("event_type") or item.get("object_type") or "").lower() in TRIGGER_EVENT_TYPES:
        event_type = str(item.get("event_type") or "").lower()
        if event_type in TRIGGER_EVENT_TYPES or item.get("event_id"):
            return True
    blob = _hay(item)
    if ISSUER_ACTION.search(blob):
        return True
    if str(item.get("kind") or "").lower() == "company_specific":
        return True
    return False


def is_event_graph_root(row: dict[str, Any] | None) -> bool:
    item = row or {}
    from_type = str(item.get("from_type") or item.get("object_type") or "").lower()
    from_node = str(item.get("from_node") or item.get("object_id") or "")
    if from_type in EVENT_NODE_TYPES:
        return True
    if from_node.startswith("bev_") or from_node.startswith("bobs_"):
        return True
    return is_trigger_event(item)


def theme_key(row: dict[str, Any] | None) -> str | None:
    item = row or {}
    if is_trigger_event(item):
        return None
    kind = str(item.get("kind") or "").lower()
    key = str(item.get("canonical_key") or "").lower()
    if kind in MARKET_WIDE_KEYS:
        return MARKET_WIDE_KEYS[kind]
    if key in MARKET_WIDE_KEYS:
        return MARKET_WIDE_KEYS[key]
    blob = _hay(item)
    if ISSUER_ACTION.search(blob):
        return None
    for token, needles in THEME_NEEDLES:
        if any(needle in blob for needle in needles):
            return token
    return None


def is_market_pricing_or_valuation_claim(row: dict[str, Any] | None) -> bool:
    item = row or {}
    claim_type = str(item.get("claim_type") or "").lower()
    if claim_type in {"valuation", "event"}:
        return True
    if str(item.get("claim_dimension") or "").lower() == "valuation_sensitivity":
        return True
    if str(item.get("claim_subject") or "").lower() == "valuation":
        return True
    blob = f"{item.get('title') or ''} {item.get('statement') or ''}"
    return bool(MARKET_PRICING_CLAIM.search(blob))


def is_fundamental_core_claim(row: dict[str, Any] | None) -> bool:
    item = row or {}
    if not item.get("is_core"):
        return False
    if str(item.get("claim_key") or "").startswith("rasm:"):
        return False
    if is_market_pricing_or_valuation_claim(item):
        return False
    claim_type = str(item.get("claim_type") or "operating").lower()
    if claim_type and claim_type not in FUNDAMENTAL_CLAIM_TYPES and claim_type != "operating":
        return False
    return True


def _trend(statuses: list[str], expectation_trends: list[str]) -> str:
    lowered = [str(item or "").lower() for item in statuses]
    if any(item in {"supported", "strengthened", "active"} for item in lowered) and any(
        item in {"rising", "improving"} for item in expectation_trends
    ):
        return "strengthening"
    if any(item in {"weakened", "weakening"} for item in lowered) or any(item == "falling" for item in expectation_trends):
        return "weakening"
    if any(item in {"retired", "closed", "fading"} for item in lowered):
        return "fading"
    return "stable"


def _direction(rows: list[dict[str, Any]]) -> str:
    blobs = " ".join(_hay(row) for row in rows)
    if any(token in blobs for token in ("cut", "miss", "fall", "down", "risk", "压缩", "下行")):
        return "down"
    if any(token in blobs for token in ("raise", "beat", "up", "strong", "expand", "上行", "增强")):
        return "up"
    return "mixed"


def _collect(store: Any, method: str) -> list[dict[str, Any]]:
    if store is None or not hasattr(store, method):
        return []
    return list(getattr(store, method)() or [])


def _cluster_sources(store: Any) -> dict[str, dict[str, list[dict[str, Any]]]]:
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def _add(kind: str, row: dict[str, Any]) -> None:
        key = theme_key(row)
        if not key:
            return
        bucket = buckets.setdefault(key, {"hypotheses": [], "attentions": [], "expectations": [], "states": [], "events": []})
        bucket[kind].append(row)

    for row in _collect(store, "list_all_hypotheses"):
        if str(row.get("status") or "") in RETIRED_HYPOTHESIS:
            continue
        if _placeholder_hypothesis(row) or is_trigger_event(row):
            continue
        if str(row.get("kind") or "") not in MARKET_WIDE_KINDS and theme_key(row) is None:
            continue
        _add("hypotheses", row)
    for row in _collect(store, "list_all_market_attentions"):
        if is_trigger_event(row):
            continue
        _add("attentions", row)
    for row in _collect(store, "list_all_expectations"):
        if is_trigger_event(row):
            continue
        _add("expectations", row)
    for row in _collect(store, "list_all_states"):
        if str(row.get("state_type") or "").lower() not in {"macro", "industry", "market_expectation"}:
            continue
        _add("states", row)
    return buckets


def _related_triggers(store: Any, key: str) -> list[dict[str, Any]]:
    out = []
    for row in _collect(store, "list_all_events"):
        if not is_trigger_event(row):
            continue
        blob = _hay(row)
        needles = next((items for token, items in THEME_NEEDLES if token == key), ())
        if needles and any(needle in blob for needle in needles):
            out.append(row)
            continue
        if key == "ai_capex_expectations" and any(token in blob for token in ("capex", "ai", "资本开支")):
            out.append(row)
    return out


def _should_promote(bucket: dict[str, list[dict[str, Any]]]) -> bool:
    hyps = bucket.get("hypotheses") or []
    tickers = {str(row.get("ticker") or "").upper() for row in hyps if row.get("ticker")}
    has_global_state = any(not row.get("ticker") for row in bucket.get("states") or [])
    if has_global_state:
        return True
    if len(tickers) >= 2:
        return True
    return False


def aggregate_dominant_drivers(store: Any) -> list[dict[str, Any]]:
    """Global MarketDominantDriver view. Never a ticker-level hypothesis passthrough."""
    clusters = _cluster_sources(store)
    drivers: list[dict[str, Any]] = []
    for key, bucket in clusters.items():
        if key == "_triggers" or not _should_promote(bucket):
            continue
        members = (bucket.get("hypotheses") or []) + (bucket.get("attentions") or []) + (bucket.get("expectations") or []) + (bucket.get("states") or [])
        if not members:
            continue
        global_states = [row for row in bucket.get("states") or [] if not row.get("ticker")]
        named = next((row for row in global_states + members if compact_text(row.get("name") or row.get("hypothesis") or row.get("statement") or "", 8)), None)
        name = compact_text(
            (named or {}).get("name")
            or (named or {}).get("hypothesis")
            or (named or {}).get("statement")
            or key.replace("_", " "),
            80,
        )
        tickers = sorted({str(row.get("ticker") or "").upper() for row in members if row.get("ticker")})
        statuses = [str(row.get("status") or "") for row in bucket.get("hypotheses") or []]
        trends = [str(row.get("trend") or "") for row in bucket.get("expectations") or []]
        confidences = [str(row.get("confidence") or "low") for row in members if row.get("confidence")]
        confidence = "high" if confidences.count("high") >= 2 else ("medium" if "medium" in confidences or "high" in confidences else "low")
        triggers = _related_triggers(store, key)
        support_ids = [str(row.get("attention_id")) for row in (bucket.get("attentions") or []) if row.get("attention_id")] + [
            str(item) for row in (bucket.get("hypotheses") or []) for item in (row.get("supporting_observations") or []) if str(item).strip()
        ]
        counter_ids = [
            str(item) for row in (bucket.get("hypotheses") or []) for item in (row.get("counter_observations") or []) if str(item).strip()
        ]
        updated = max((_sort_time(row, "updated_at", "created_at") for row in members), default="")
        started = min((_sort_time(row, "created_at", "started_at") for row in members if _sort_time(row, "created_at", "started_at")), default=updated)
        basis = "global_environment" if global_states else "ticker_cluster"
        # Ticker coverage says nothing about the market importance of a theme.
        importance = "medium" if global_states else "low"
        why = compact_text(
            next((row.get("why_it_matters") or row.get("reason") or row.get("statement") or "" for row in members if row.get("why_it_matters") or row.get("reason") or row.get("statement")), ""),
            240,
        )
        drivers.append(
            {
                "id": f"gmdd_{key}",
                "name": name,
                "category": key,
                "importance": importance,
                "assessment_basis": basis,
                "direction": _direction(members),
                "confidence": confidence,
                "trend": _trend(statuses, trends),
                "supporting_signal_ids": list(dict.fromkeys(support_ids))[:12],
                "counter_signal_ids": list(dict.fromkeys(counter_ids))[:12],
                "trigger_event_ids": [str(row.get("event_id")) for row in triggers if row.get("event_id")][:12],
                "affected_asset_classes": [],
                "affected_sectors": [],
                "affected_tickers": tickers,
                "started_at": started or None,
                "updated_at": updated or None,
                "status": "candidate",
                "why_it_matters": why or None,
                "source_object_ids": [str(row.get("hypothesis_id") or row.get("attention_id") or row.get("expectation_id") or row.get("state_id") or "") for row in members if row.get("hypothesis_id") or row.get("attention_id") or row.get("expectation_id") or row.get("state_id")][:16],
            }
        )
    drivers.sort(key=lambda row: ({"very_high": 0, "high": 1, "medium": 2, "low": 3}.get(str(row.get("importance")), 4), str(row.get("updated_at") or "")), reverse=False)
    return drivers[:3]


def _sensitivity_band(exposures: list[dict[str, Any]], drivers: list[dict[str, Any]]) -> str:
    if any(str(row.get("magnitude") or "").lower() in {"high", "large", "strong"} for row in exposures):
        return "high"
    if exposures or drivers:
        return "medium"
    return "unknown"


def _relevance_band(hypotheses: list[dict[str, Any]], attentions: list[dict[str, Any]], events: list[dict[str, Any]]) -> str:
    if any(str(row.get("status") or "").lower() in {"supported", "active"} for row in hypotheses) and attentions:
        return "high"
    if hypotheses or attentions or events:
        return "medium"
    return "low"


def _theme_match(row: dict[str, Any], key: str) -> bool:
    if theme_key(row) == key:
        return True
    blob = _hay(row)
    needles = next((items for token, items in THEME_NEEDLES if token == key), ())
    return any(needle in blob for needle in needles)


def ticker_sensitivities(store: Any, ticker: str, drivers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """TickerMarketSensitivity view. Trigger events never become rows. sensitivity ≠ current_relevance."""
    symbol = str(ticker or "").upper()
    live_drivers = drivers if drivers is not None else aggregate_dominant_drivers(store)
    if not live_drivers:
        return []
    exposures = [row for row in _rows(store, "list_exposures", symbol) if not is_trigger_event(row)]
    value_drivers = _rows(store, "list_drivers", symbol)
    hypotheses = [row for row in _rows(store, "list_hypotheses", symbol) if not is_trigger_event(row) and not _placeholder_hypothesis(row)]
    attentions = [row for row in _rows(store, "list_market_attentions", symbol) if not is_trigger_event(row)]
    events = [row for row in _rows(store, "list_events", symbol) if is_trigger_event(row)]
    rows: list[dict[str, Any]] = []
    for driver in live_drivers:
        key = str(driver.get("category") or "")
        matched_exp = [row for row in exposures if _theme_match(row, key)]
        matched_drv = [row for row in value_drivers if _theme_match(row, key)]
        matched_hyp = [row for row in hypotheses if _theme_match(row, key)]
        matched_att = [row for row in attentions if _theme_match(row, key)]
        related_events = [row for row in events if _theme_match(row, key)]
        if not (matched_exp or matched_drv or matched_hyp):
            continue
        mechanism = compact_text(
            next((row.get("mechanism") or row.get("why_it_matters") or row.get("current_state") or "" for row in matched_exp + matched_drv if row.get("mechanism") or row.get("why_it_matters") or row.get("current_state")), ""),
            200,
        )
        confidence = next((str(row.get("confidence") or "medium") for row in matched_hyp + matched_drv if row.get("confidence")), "medium")
        rows.append(
            {
                "ticker": symbol,
                "market_driver_id": driver.get("id"),
                "sensitivity": _sensitivity_band(matched_exp, matched_drv),
                "current_relevance": _relevance_band(matched_hyp, matched_att, related_events),
                "confidence": confidence,
                "mechanism": mechanism or None,
                "linked_exposure_ids": [str(row.get("exposure_id")) for row in matched_exp if row.get("exposure_id")][:8],
                "linked_driver_ids": [str(row.get("driver_id")) for row in matched_drv if row.get("driver_id")][:8],
            }
        )
    return rows


def recent_driver_changes(store: Any, drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    member_ids = {str(token) for row in drivers for token in (row.get("source_object_ids") or []) if token}
    if not member_ids or not hasattr(store, "list_all_history"):
        return []
    out = []
    for row in store.list_all_history():
        if str(row.get("object_id") or "") not in member_ids:
            continue
        if str(row.get("object_type") or "") not in {"market_driver_hypothesis", "market_attention", "expectation", "macro_state", "industry_state"}:
            continue
        before = dict(row.get("from_payload") or {})
        after = dict(row.get("to_payload") or {})
        if not before:
            continue
        skip = {"updated_at", "created_at", "last_reviewed_at", "run_id", "snapshot_id", "history_id"}
        deltas = [{"field": key, "from": before.get(key), "to": after.get(key)} for key in sorted(set(before) | set(after)) if key not in skip and before.get(key) != after.get(key)]
        if not deltas:
            continue
        out.append(
            {
                "history_id": row.get("history_id"),
                "object_type": row.get("object_type"),
                "object_id": row.get("object_id"),
                "deltas": deltas,
                "reason": compact_text(row.get("reason") or "", 200) or None,
                "created_at": row.get("created_at"),
            }
        )
    out.sort(key=lambda item: _sort_time(item, "created_at"), reverse=True)
    return out[:8]


def driver_display_name(row: dict[str, Any] | None) -> str:
    item = row or {}
    theme = THEME_DISPLAY_ZH.get(str(item.get("category") or ""))
    if theme:
        return theme
    return compact_text(item.get("name") or "", 80)


def pricing_axis(drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "role": ROLE_LABELS[idx] if idx < len(ROLE_LABELS) else "辅助",
            "driver_id": row.get("id"),
            "name": driver_display_name(row) or row.get("name"),
        }
        for idx, row in enumerate(drivers)
    ]


def structural_paths(store: Any, ticker: str, *, limit: int = 5) -> list[dict[str, Any]]:
    edges = _rows(store, "list_causal_edges", ticker)
    paths = []
    for edge in edges:
        if is_event_graph_root(edge):
            continue
        if str(edge.get("status") or "") in {"deprecated", "challenged"}:
            continue
        paths.append(
            {
                "from_node": edge.get("from_node"),
                "to_node": edge.get("to_node"),
                "from_type": edge.get("from_type"),
                "to_type": edge.get("to_type"),
                "relationship_type": edge.get("relationship_type"),
                "mechanism": compact_text(edge.get("mechanism") or edge.get("statement") or "", 200) or None,
                "status": edge.get("status"),
                "evidence_ids": list(edge.get("evidence_ids") or edge.get("support_evidence_ids") or [])[:8],
            }
        )
        if len(paths) >= limit:
            break
    return paths


def _price_status(grade: str | None, unexplained: bool, explanation_count: int) -> str:
    token = str(grade or "").lower()
    if token in {"well_explained"} and explanation_count and not unexplained:
        return PRICE_EXPLAINED
    if token in {"largely_unexplained"} or (unexplained and explanation_count == 0):
        return PRICE_UNEXPLAINED
    if explanation_count or token in {"partially_explained"} or unexplained:
        return PRICE_PARTIAL
    return PRICE_UNEXPLAINED if not explanation_count else PRICE_PARTIAL


def price_attribution(
    store: Any,
    ticker: str,
    *,
    drivers: list[dict[str, Any]],
    sensitivities: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    hyps = hypotheses if hypotheses is not None else [row for row in _rows(store, "list_hypotheses", symbol) if not _placeholder_hypothesis(row)]
    divergences = [row for row in _rows(store, "list_divergences", symbol) if str(row.get("status") or "") in UNRESOLVED_DIVERGENCE]
    events = _rows(store, "list_events", symbol)
    explanations: list[dict[str, Any]] = []
    for row in drivers:
        explanations.append({"kind": "global_driver", "id": row.get("id"), "label": row.get("name"), "forced_unique": False})
    for row in sensitivities:
        explanations.append({"kind": "sensitivity", "id": row.get("market_driver_id"), "label": row.get("mechanism"), "forced_unique": False})
    for row in hyps[:4]:
        explanations.append(
            {
                "kind": "ticker_hypothesis",
                "id": row.get("hypothesis_id"),
                "label": compact_text(row.get("hypothesis") or row.get("name") or "", 160),
                "forced_unique": False,
            }
        )
    for row in events[:2]:
        if is_trigger_event(row):
            explanations.append(
                {
                    "kind": "company_event",
                    "id": row.get("event_id"),
                    "label": compact_text(row.get("title") or "", 160),
                    "forced_unique": False,
                }
            )
    latest = divergences[0] if divergences else None
    unresolved_q = compact_text((latest or {}).get("unresolved_question") or "", 200) or None
    status = (
        _price_status((latest or {}).get("explanation_grade"), bool(unresolved_q or divergences), len(explanations))
        if latest else PRICE_NOT_ASSESSED
    )
    return {
        "status": status,
        "explanations": explanations,
        "explained": [row for row in explanations if row.get("kind") in {"global_driver", "ticker_hypothesis", "sensitivity"}] if latest else [],
        "unexplained": [{"question": unresolved_q, "divergence_id": (latest or {}).get("divergence_id")}] if unresolved_q else [],
        "forced_single_cause": False,
        "price_is_not_claim_invalidation": True,
        "divergence": {
            "latest": latest,
            "unresolved": divergences[:2],
        },
    }


def _quote(store: Any, ticker: str, research: Any | None) -> dict[str, Any]:
    header = {}
    if store is not None and hasattr(store, "latest_run"):
        header = ((store.latest_run(ticker) or {}).get("header") or {})
    pack = research.get_pack(ticker) if research and hasattr(research, "get_pack") else {}
    profile = (pack or {}).get("company_profile") or {}
    price = header.get("last_price") or header.get("price") or profile.get("last_price") or profile.get("price")
    change = header.get("day_change_pct") or header.get("change_pct") or profile.get("day_change_pct")
    return {
        "price": price,
        "day_change_pct": change,
        "empty": price is None,
    }


def _thesis_card(store: Any, ticker: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
    invest = investment_snapshot(store, ticker)
    thesis = invest.get("current_thesis") or {}
    by_id = {str(row.get("claim_id")): row for row in claims}
    def _named(ids: list[Any]) -> list[dict[str, Any]]:
        out = []
        for cid in ids or []:
            row = by_id.get(str(cid))
            if row:
                out.append({"claim_id": row.get("claim_id"), "title": row.get("title"), "status": row.get("status")})
        return out
    if not thesis:
        return {
            "current_thesis": None,
            "confidence": None,
            "top_supporting_claims": [],
            "top_risk_claims": [],
            "what_would_change_thesis": None,
            "empty": True,
        }
    return {
        "thesis_id": thesis.get("thesis_id"),
        "current_thesis": thesis.get("current_thesis") or None,
        "confidence": thesis.get("confidence"),
        "top_supporting_claims": _named(list(thesis.get("top_supporting_claim_ids") or [])),
        "top_risk_claims": _named(list(thesis.get("top_risk_claim_ids") or [])),
        "what_would_change_thesis": compact_text(thesis.get("what_would_change_thesis") or "", 240) or None,
        "key_upside_condition": compact_text(thesis.get("key_upside_condition") or "", 200) or None,
        "key_downside_condition": compact_text(thesis.get("key_downside_condition") or "", 200) or None,
        "empty": not bool(thesis.get("current_thesis")),
    }


def filter_core_claim_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_fundamental_core_claim(row)][:CORE_CLAIM_MAX]


def _has_cjk(text: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _label_lookup(store: Any, method: str, id_key: str, *text_keys: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _collect(store, method):
        sid = str(row.get(id_key) or "").strip()
        if not sid:
            continue
        options = [row.get(key) for key in text_keys if row.get(key)]
        label = compact_text(next((value for value in options if _has_cjk(value)), options[0] if options else ""), 160)
        if label:
            out[sid] = label
    return out


def _labeled_items(ids: list[Any], lookup: dict[str, str], *, title_key: str = "label") -> list[dict[str, str]]:
    out = []
    for raw in ids or []:
        sid = str(raw or "").strip()
        if sid in lookup:
            out.append({"id": sid, title_key: lookup[sid]})
    return out


def decorate_market_overview(payload: dict[str, Any], store: Any) -> dict[str, Any]:
    """Attach display labels for the market page. Still a read-only view; no GLM."""
    attentions = _label_lookup(store, "list_all_market_attentions", "attention_id", "statement", "name")
    events = _label_lookup(store, "list_all_events", "event_id", "title", "subject")
    layered_triggers: list[dict[str, str]] = []
    seen_triggers: set[str] = set()
    updated_at = ""
    for row in payload.get("dominant_drivers") or []:
        row["display_name"] = driver_display_name(row) or compact_text(row.get("name") or "", 80)
        row["supporting_signals"] = _labeled_items(row.get("supporting_signal_ids") or [], attentions)
        row["counter_signals"] = _labeled_items(row.get("counter_signal_ids") or [], attentions)
        landing = row.get("display_name") or ""
        row["trigger_events"] = []
        for item in _labeled_items(row.get("trigger_event_ids") or [], events, title_key="title"):
            item["lands_on"] = landing
            row["trigger_events"].append(item)
            if item["id"] not in seen_triggers:
                seen_triggers.add(item["id"])
                layered_triggers.append(item)
        stamp = str(row.get("updated_at") or "")
        if stamp > updated_at:
            updated_at = stamp
    payload["trigger_events"] = layered_triggers
    payload["as_of"] = updated_at or None
    for axis in payload.get("pricing_axis") or []:
        match = next((row for row in (payload.get("dominant_drivers") or []) if row.get("id") == axis.get("driver_id")), None)
        if match and match.get("display_name"):
            axis["name"] = match["display_name"]
    for change in payload.get("recent_driver_changes") or []:
        change["kind_label"] = CHANGE_KIND_ZH.get(str(change.get("object_type") or ""), "主轴")
        reason = compact_text(change.get("reason") or "", 160)
        change["summary"] = reason if reason and _has_cjk(reason) else "近窗记录到实质变化"
    return payload


def build_market_overview(store: Any, *, research: Any | None = None) -> dict[str, Any]:
    del research
    drivers = aggregate_dominant_drivers(store)
    empty = not drivers
    # The current read model has no persisted cross-asset or sector observations.
    # A promoted ticker cluster is therefore a candidate, not a verified market conclusion.
    payload = {
        "source": "persisted_brain",
        "llm_invoked": False,
        "market_state": "empty" if empty else "provisional",
        "assessment_basis": "global_environment" if any(row.get("assessment_basis") == "global_environment" for row in drivers) else ("ticker_cluster" if drivers else None),
        "coverage_gaps": [] if empty else ["cross_asset", "sector_breadth"],
        "served_at": datetime.now(timezone.utc).isoformat(),
        "empty_state": EMPTY_DOMINANT if empty else None,
        # A ranked pricing axis requires independent cross-asset confirmation.
        "pricing_axis": [],
        "dominant_drivers": drivers,
        "recent_driver_changes": recent_driver_changes(store, drivers),
        "cross_asset_summary": [],
        "sector_summary": [],
        "covered_tickers": sorted({ticker for row in drivers for ticker in row.get("affected_tickers") or []}),
    }
    return decorate_market_overview(payload, store)


def attach_company_overview(snapshot: dict[str, Any], store: Any, ticker: str, *, research: Any | None = None) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    drivers = aggregate_dominant_drivers(store)
    sensitivities = ticker_sensitivities(store, symbol, drivers)
    raw_cores = [row for row in _rows(store, "list_active_claims", symbol) if row.get("is_core")]
    snapshot["core_claims"] = [row for row in (snapshot.get("core_claims") or []) if not is_market_pricing_or_valuation_claim(row)][:CORE_CLAIM_MAX]
    snapshot["valuation_or_market_claims"] = [
        {
            "claim_id": row.get("claim_id"),
            "title": row.get("title"),
            "claim_type": row.get("claim_type"),
            "claim_dimension": row.get("claim_dimension"),
        }
        for row in raw_cores
        if is_market_pricing_or_valuation_claim(row)
    ]
    snapshot["thesis"] = _thesis_card(store, symbol, snapshot["core_claims"])
    snapshot["quote"] = _quote(store, symbol, research)
    snapshot["market_environment"] = {
        "dominant_drivers": decorate_market_overview({"dominant_drivers": drivers, "pricing_axis": [], "recent_driver_changes": []}, store)["dominant_drivers"],
        "sensitivities": sensitivities,
        "empty": not drivers,
        "empty_state": EMPTY_DOMINANT if not drivers else None,
    }
    claim_stamps = [str(row.get("updated_at") or row.get("created_at") or "") for row in raw_cores]
    snapshot["freshness"] = {
        "brain_run_at": snapshot.get("as_of"),
        "claims_updated_at": max(claim_stamps, default="") or None,
        "market_updated_at": max((str(row.get("updated_at") or "") for row in drivers), default="") or None,
        "quote_updated_at": None,
        "served_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot["price_attribution"] = price_attribution(
        store,
        symbol,
        drivers=drivers,
        sensitivities=sensitivities,
        hypotheses=list((snapshot.get("market_view") or {}).get("active_hypotheses") or []),
    )
    snapshot["structural_paths"] = structural_paths(store, symbol)
    invest = investment_snapshot(store, symbol)
    snapshot["financial_summary"] = (invest.get("financial_impacts") or [])[:5]
    snapshot["scenario_summary"] = [
        {
            "scenario_id": row.get("scenario_id"),
            "scenario_type": row.get("scenario_type"),
            "probability_band": row.get("probability_band"),
            "confidence": row.get("confidence"),
        }
        for row in (invest.get("scenarios") or [])
    ]
    snapshot["valuation_summary"] = invest.get("valuation_state")
    snapshot["llm_invoked"] = False
    snapshot["source"] = snapshot.get("source") or "persisted_brain"
    return snapshot


def persistable_invalidate(claim: dict[str, Any] | None, reasoning: dict[str, Any] | None = None) -> list[str]:
    item = claim or {}
    reason = reasoning if isinstance(reasoning, dict) else (item.get("reasoning") if isinstance(item.get("reasoning"), dict) else {})
    texts = [
        item.get("what_would_invalidate"),
        reason.get("what_would_invalidate"),
        reason.get("what_invalidates"),
        reason.get("what_would_change_this_claim"),
    ]
    out = []
    for text in texts:
        if isinstance(text, list):
            out.extend(compact_text(str(item), 240) for item in text if compact_text(str(item), 8))
        else:
            cleaned = compact_text(text or "", 240)
            if cleaned:
                out.append(cleaned)
    return list(dict.fromkeys(out))


def attach_claim_detail(payload: dict[str, Any], store: Any, ticker: str, *, research: Any | None = None) -> dict[str, Any]:
    claim = payload.get("claim") or {}
    reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
    from .pm_view import _claim_recent_change

    history = _rows(store, "list_history", ticker)
    payload["llm_invoked"] = False
    payload["source"] = "persisted_brain"
    payload["recent_change"] = _claim_recent_change(store, ticker, claim, history)
    payload["what_would_invalidate"] = persistable_invalidate(claim, reasoning)
    invest = investment_snapshot(store, ticker)
    claim_id = str(claim.get("claim_id") or "")
    payload["financial_impacts"] = [row for row in (invest.get("financial_impacts") or []) if str(row.get("claim_id") or "") == claim_id]
    payload["scenarios"] = [
        {
            "scenario_id": row.get("scenario_id"),
            "scenario_type": row.get("scenario_type"),
            "probability_band": row.get("probability_band"),
            "linked": claim_id in [str(item) for item in (row.get("linked_claim_ids") or [])],
        }
        for row in (invest.get("scenarios") or [])
    ]
    payload["valuation_sensitivity"] = invest.get("valuation_state")
    payload["market_pricing_assumptions"] = [
        {
            "hypothesis_id": row.get("hypothesis_id"),
            "hypothesis": compact_text(row.get("hypothesis") or row.get("name") or "", 200),
            "status": row.get("status"),
            "confidence": row.get("confidence"),
        }
        for row in _rows(store, "list_hypotheses", ticker)
        if not _placeholder_hypothesis(row) and str(row.get("status") or "") not in RETIRED_HYPOTHESIS
    ][:4]
    payload["price_feedback"] = {
        "price_is_not_claim_invalidation": True,
        "divergences": [row for row in _rows(store, "list_divergences", ticker) if str(row.get("status") or "") in UNRESOLVED_DIVERGENCE][:2],
    }
    payload["claim_history"] = payload.get("history") or []
    del research
    return payload
