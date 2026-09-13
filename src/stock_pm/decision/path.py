"""Visible rates path + selective macro display. VIX never implies a stock print."""

from __future__ import annotations

from typing import Any

from .causal import CHANNEL_DURATION, RATES_DISCOUNT_MECHANISM, canonical_metric
from .change import ChangeSnapshot

BACKGROUND_METRICS = frozenset({"gold", "wti", "broad_usd_proxy", "usd_broad", "dxy"})
RATES_CAUSE_METRICS = frozenset({"cpi", "core_cpi", "pce", "core_pce", "inflation"})
RATES_CONFIRM_METRICS = frozenset({"us2y", "real_rate", "cut_odds"})
LABOR_METRICS = frozenset({"nfp"})
RISK_METRICS = frozenset({"vix"})

RATES_INVALIDATION = (
    "若 CPI 回落且 US2Y 未再走高、或个股久期暴露消失，则利率→折现率→高估值承压链失效；"
    "VIX 变化不能单独作为个股涨跌结论"
)
VIX_INVALIDATION = (
    "VIX 回落到阈值内且没有行业/暴露传导时，风险状态撤销；"
    "禁止把 VIX 升跌直接写成某只股票的涨跌方向"
)


def has_duration_exposure(watch: dict[str, Any] | None, symbol: str) -> bool:
    row = watch or {}
    themes = [str(item) for item in (row.get("themes") or [])]
    rate = str(row.get("rate_sensitivity") or "medium")
    return rate == "high" or "high_valuation_growth" in themes


def macro_display_lane(metric: str, watch: dict[str, Any] | None, symbol: str) -> str:
    key = canonical_metric(metric)
    if key in BACKGROUND_METRICS or key in LABOR_METRICS:
        return "background"
    if key in RISK_METRICS:
        return "risk"
    if key in RATES_CAUSE_METRICS or key in RATES_CONFIRM_METRICS:
        return "main" if has_duration_exposure(watch, symbol) else "background"
    return "background"


def _change_of(changes: list[ChangeSnapshot], metric: str) -> ChangeSnapshot | None:
    wanted = canonical_metric(metric)
    for row in changes:
        if canonical_metric(row.metric) == wanted:
            return row
    return None


def build_risk_state(changes: list[ChangeSnapshot]) -> dict[str, Any] | None:
    vix = _change_of(changes, "vix")
    if vix is None:
        return None
    if vix.direction == "up" and vix.materiality == "material":
        status = "elevated"
    elif vix.direction == "down" and vix.materiality == "material":
        status = "eased"
    else:
        status = "steady"
    return {
        "metric": "vix",
        "status": status,
        "direction": vix.direction,
        "materiality": vix.materiality,
        "current": vix.current_value,
        "previous": vix.previous_value,
        "delta": vix.delta,
        "unit": vix.unit or "index",
        "as_of": vix.current_as_of,
        "series": "VIXCLS",
        "source": (vix.fact_refs[0].source if vix.fact_refs else "FRED"),
        "http_source": (vix.fact_refs[0].http_source if vix.fact_refs and getattr(vix.fact_refs[0], "http_source", None) else None),
        "affects": "risk_state",
        "does_not_imply": "个股涨跌方向",
        "invalidation": VIX_INVALIDATION,
        "confidence": "high" if vix.materiality == "material" else "limited",
    }


def build_rates_path(
    *,
    symbol: str,
    watch: dict[str, Any] | None,
    changes: list[ChangeSnapshot],
    confirmation: Any,
    facts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not has_duration_exposure(watch, symbol):
        return {
            "id": "rates_discount_duration",
            "status": "not_applicable",
            "reason": "该标的没有高估值久期暴露，利率贴现链不进入个股主结论",
            "nodes": [],
            "edges": [],
        }

    def _fact_field(metric: str, key: str) -> Any:
        wanted = canonical_metric(metric)
        for row in facts or []:
            if canonical_metric(str(row.get("metric") or "")) == wanted:
                return row.get(key)
        return None

    cpi = _change_of(changes, "cpi")
    us2y = _change_of(changes, "us2y")
    price = next((row for row in changes if canonical_metric(row.metric) == "close" and row.subject == symbol), None)
    if cpi is None and us2y is None:
        return None
    confirm_status = getattr(confirmation, "status", None) or "insufficient"
    confidence = "high" if confirm_status == "confirmed" and cpi and cpi.materiality == "material" else "limited"
    direction = "pressure" if (cpi and cpi.direction == "up") or (us2y and us2y.direction == "up") else "watch"
    nodes = [
        {
            "id": "cpi",
            "layer": "fact",
            "title": "CPI",
            "metric": "cpi",
            "direction": None if cpi is None else cpi.direction,
            "value": None if cpi is None else cpi.current_value,
            "previous": None if cpi is None else cpi.previous_value,
            "unit": "index",
            "series": "CPIAUCSL",
            "as_of": None if cpi is None else cpi.current_as_of,
            "source": (cpi.fact_refs[0].source if cpi and cpi.fact_refs else "FRED"),
            "status": "ok" if cpi else "missing",
            "origin": "primary",
            "http_source": _fact_field("cpi", "http_source"),
        },
        {
            "id": "us2y",
            "layer": "change",
            "title": "US2Y / 利率确认",
            "metric": "us2y",
            "direction": None if us2y is None else us2y.direction,
            "value": None if us2y is None else us2y.current_value,
            "previous": None if us2y is None else us2y.previous_value,
            "unit": "percent",
            "series": "DGS2",
            "as_of": None if us2y is None else us2y.current_as_of,
            "source": (us2y.fact_refs[0].source if us2y and us2y.fact_refs else "FRED"),
            "status": "ok" if us2y else "missing",
            "origin": "primary",
            "http_source": _fact_field("us2y", "http_source"),
        },
        {
            "id": "discount",
            "layer": "expectation",
            "title": "贴现率 / 加息预期",
            "mechanism": RATES_DISCOUNT_MECHANISM,
            "direction": direction,
            "status": confirm_status,
            "confidence": confidence,
        },
        {
            "id": "industry",
            "layer": "impact",
            "title": "高估值科技行业",
            "theme": "high_valuation_growth",
            "channel": CHANNEL_DURATION,
            "direction": direction,
        },
        {
            "id": "exposure",
            "layer": "impact",
            "title": f"{symbol} 久期暴露",
            "target": symbol,
            "channel": CHANNEL_DURATION,
            "direction": direction,
        },
        {
            "id": "price_pressure",
            "layer": "what_changes",
            "title": "价格压力（观察，不是已定价方向）",
            "metric": "close",
            "value": None if price is None else price.current_value,
            "previous": None if price is None else price.previous_value,
            "as_of": None if price is None else price.current_as_of,
            "direction": None if price is None else price.direction,
            "does_not_imply": "个股交易指令",
        },
    ]
    edges = [
        {
            "from": "cpi",
            "to": "us2y",
            "direction": "tightening" if direction == "pressure" else "watch",
            "mechanism": "inflation_to_nominal_rates",
            "as_of": (cpi.current_as_of if cpi else None) or (us2y.current_as_of if us2y else None),
            "confidence": confidence,
            "invalidation": RATES_INVALIDATION,
            "evidence": ["cpi", "us2y"],
        },
        {
            "from": "us2y",
            "to": "discount",
            "direction": "higher_discount" if direction == "pressure" else "watch",
            "mechanism": RATES_DISCOUNT_MECHANISM,
            "as_of": us2y.current_as_of if us2y else None,
            "confidence": confidence,
            "invalidation": RATES_INVALIDATION,
            "evidence": ["us2y"],
        },
        {
            "from": "discount",
            "to": "industry",
            "direction": "duration_pressure",
            "mechanism": CHANNEL_DURATION,
            "as_of": us2y.current_as_of if us2y else None,
            "confidence": confidence,
            "invalidation": RATES_INVALIDATION,
            "evidence": ["us2y"],
        },
        {
            "from": "industry",
            "to": "exposure",
            "direction": "company_exposure",
            "mechanism": CHANNEL_DURATION,
            "as_of": None,
            "confidence": confidence,
            "invalidation": RATES_INVALIDATION,
            "evidence": ["watchlist.themes"],
        },
        {
            "from": "exposure",
            "to": "price_pressure",
            "direction": "observe_only",
            "mechanism": "exposure_to_price_pressure",
            "as_of": price.current_as_of if price else None,
            "confidence": "limited",
            "invalidation": RATES_INVALIDATION,
            "evidence": ["close"],
        },
    ]
    return {
        "id": "rates_discount_duration",
        "status": "visible",
        "confidence": confidence,
        "direction": direction,
        "horizon": "short",
        "invalidation": RATES_INVALIDATION,
        "nodes": nodes,
        "edges": edges,
    }


def split_display_facts(
    facts: list[dict[str, Any]],
    changes: list[ChangeSnapshot],
    watch: dict[str, Any] | None,
    symbol: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main: list[dict[str, Any]] = []
    background: list[dict[str, Any]] = []
    for row in facts:
        metric = canonical_metric(str(row.get("metric") or ""))
        lane = "main"
        if row.get("kind") == "macro":
            lane = macro_display_lane(metric, watch, symbol)
        if lane in {"background", "risk"}:
            background.append(row)
        else:
            main.append(row)
    return main, background
