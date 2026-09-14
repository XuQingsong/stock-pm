"""Phase 6B: multi-chain driver synthesis. Structured rules only. No LLM.

Consumes Phase 6A macro chains. Only status=ok chains are directional
evidence. Degraded/unavailable rows enter missing notes, never a vote.
Confidence uses independent channels + freshness + completeness +
counter-evidence. Same-fact derivatives do not double-count. VIX never
sets direction. can_form_direction stays false.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from .exposure import why_relevant
from .macro_chain import (
    LAYER_ORDER,
    clickable_source_url,
    stock_macro_chains,
)
from .policy import is_safe_public_http_url
from .types import TrustedEvent


SYNTHESIS_SYMBOLS = ("NVDA", "XOM", "JPM", "AAPL", "NOK")
INDUSTRY_LABELS = {
    "semis": "半导体 / 高估值成长",
    "energy": "能源生产",
    "banks": "银行 / 信用",
}
INDUSTRY_CHANNELS = {
    "semis": frozenset({"duration", "supply_chain"}),
    "energy": frozenset({"commodity_revenue"}),
    "banks": frozenset({"credit_conditions"}),
}
INDUSTRY_SYMBOLS = {
    "semis": ("NVDA",),
    "energy": ("XOM",),
    "banks": ("JPM",),
}

THEME_OF_METRIC = {
    "cpi": "rates",
    "core_cpi": "rates",
    "nfp": "rates",
    "us2y": "rates",
    "vix": "risk",
    "wti": "energy",
    "oil": "energy",
    "broad_usd_proxy": "fx",
    "credit": "credit",
    "war_sanctions": "geopolitics",
    "energy_supply": "energy",
    "inflation_employment": "rates",
    "policy_rate": "rates",
}

CHANNEL_KIND = {
    "cpi": "official_inflation",
    "core_cpi": "official_inflation",
    "nfp": "official_labor",
    "us2y": "market_yield",
    "vix": "risk_index",
    "wti": "energy_price",
    "oil": "energy_price",
    "broad_usd_proxy": "fx_price",
    "credit": "credit_event",
    "war_sanctions": "geo_event",
    "energy_supply": "energy_event",
    "inflation_employment": "official_inflation",
    "policy_rate": "market_yield",
}

THEME_LABEL = {
    "rates": "利率 / 折现率",
    "energy": "能源 / 油价",
    "fx": "美元 / 海外收入折算",
    "credit": "信用 / 融资",
    "geopolitics": "地缘 / 制裁",
    "risk": "风险确认",
}

PRESSURE_STANCES = frozenset({
    "cut_odds_delayed",
    "cut_odds_delayed_conditional",
    "higher_discount",
    "higher_energy_cost",
    "stronger_usd",
})
RELIEF_STANCES = frozenset({
    "cut_odds_earlier",
    "lower_discount",
})
DIRECTIONAL_THEMES = frozenset({"rates", "energy", "fx", "credit", "geopolitics"})
CONFIDENCE_RANK = {
    "insufficient": 0,
    "limited": 1,
    "medium": 2,
    "high": 3,
}
METRIC_EVENT_TYPE = {
    "cpi": "inflation_employment",
    "core_cpi": "inflation_employment",
    "nfp": "inflation_employment",
    "us2y": "central_bank_rates",
    "vix": "vix_risk",
    "wti": "energy_supply",
    "oil": "energy_supply",
    "broad_usd_proxy": "fx_usd",
    "credit": "sovereign_or_corporate_debt",
    "war_sanctions": "war_sanctions",
    "energy_supply": "energy_supply",
    "inflation_employment": "inflation_employment",
    "policy_rate": "central_bank_rates",
}
# Monthly official prints vs daily market series vs event documents.
FRESHNESS_WINDOWS = {
    "cpi": 45,
    "core_cpi": 45,
    "nfp": 45,
    "inflation_employment": 45,
    "us2y": 7,
    "vix": 7,
    "wti": 7,
    "oil": 7,
    "broad_usd_proxy": 7,
    "policy_rate": 14,
    "credit": 30,
    "war_sanctions": 30,
    "energy_supply": 14,
}
DAILY_METRICS = frozenset({"us2y", "vix", "wti", "oil", "broad_usd_proxy"})


def _layer(chain: dict[str, Any], name: str) -> dict[str, Any]:
    for row in chain.get("layers") or []:
        if row.get("id") == name:
            return row
    return {}


def _safe_refs(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("source_url") or row.get("canonical_url") or "").strip()
        if not is_safe_public_http_url(url) or url in seen:
            continue
        seen.add(url)
        out.append({
            "source_id": row.get("source_id") or url,
            "source_url": url,
            "publisher": row.get("publisher") or "",
            "source_tier": row.get("source_tier") or 1,
            "content_type": row.get("content_type") or "official_fact",
            "fact_or_opinion": row.get("fact_or_opinion") or "fact",
            "as_of": row.get("as_of"),
            "series": row.get("series"),
        })
    return out


def chain_evidence_refs(chain: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for layer in chain.get("layers") or []:
        refs.extend(layer.get("evidence_refs") or [])
    if not refs:
        url = clickable_source_url(chain)
        if url:
            refs.append({"source_url": url, "publisher": chain.get("family") or "official"})
    return _safe_refs(refs)


def fact_key(chain: dict[str, Any]) -> str:
    refs = chain_evidence_refs(chain)
    if refs:
        return str(refs[0]["source_url"]).rstrip("/").lower()
    series = ""
    fact = _layer(chain, "fact")
    for ref in fact.get("evidence_refs") or []:
        series = str(ref.get("series") or "")
        if series:
            break
    series = series or str(chain.get("metric") or "")
    period = str(chain.get("period") or "")
    if series and period:
        return f"{series}:{period}"
    return str(chain.get("chain_id") or "unknown")


def _theme(chain: dict[str, Any]) -> str:
    metric = str(chain.get("metric") or "")
    family = str(chain.get("family") or "")
    event_type = str(chain.get("event_type") or "")
    return (
        THEME_OF_METRIC.get(metric)
        or THEME_OF_METRIC.get(event_type)
        or {"inflation": "rates", "labor": "rates", "rates": "rates"}.get(family)
        or family
        or "other"
    )


def _channel_kind(chain: dict[str, Any]) -> str:
    metric = str(chain.get("metric") or "")
    return CHANNEL_KIND.get(metric) or CHANNEL_KIND.get(str(chain.get("event_type") or "")) or _theme(chain)


def _change_direction(chain: dict[str, Any]) -> str | None:
    change = _layer(chain, "change")
    direction = change.get("direction")
    return str(direction) if direction in {"up", "down", "unchanged"} else None


def _stance(chain: dict[str, Any]) -> str:
    return str(_layer(chain, "expectation").get("stance") or "")


def polarity(chain: dict[str, Any]) -> str | None:
    theme = _theme(chain)
    if theme == "risk":
        direction = _change_direction(chain)
        return "risk_up" if direction == "up" else "risk_down" if direction == "down" else "present"
    stance = _stance(chain)
    if stance in PRESSURE_STANCES:
        return "pressure"
    if stance in RELIEF_STANCES:
        return "relief"
    direction = _change_direction(chain)
    if theme in {"rates", "energy", "fx"} and direction == "up":
        return "pressure"
    if theme in {"rates", "energy", "fx"} and direction == "down":
        return "relief"
    if theme in {"credit", "geopolitics"}:
        return "present"
    return None


def _is_vix(chain: dict[str, Any]) -> bool:
    return chain.get("metric") == "vix" or chain.get("vix_role") == "risk_confirmation_only" and chain.get("metric") == "vix"


def _is_directional_ok(chain: dict[str, Any]) -> bool:
    return (
        chain.get("status") == "ok"
        and not _is_vix(chain)
        and _theme(chain) in DIRECTIONAL_THEMES
        and polarity(chain) is not None
    )


def _period(chain: dict[str, Any]) -> str:
    return str(chain.get("period") or "")[:10]


def _as_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def freshness_window_days(chain: dict[str, Any]) -> int:
    metric = str(chain.get("metric") or "")
    return int(FRESHNESS_WINDOWS.get(metric, 30))


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _injected_clock() -> date | None:
    stamp = _as_date(os.getenv("STOCK_PM_SYNTHESIS_NOW"))
    if stamp is None:
        return None
    env = (os.getenv("APP_ENV") or "").strip().lower()
    mode = (os.getenv("STOCK_PM_EVENTS_MODE") or "").strip().lower()
    if env in {"test", "development", "local"} or mode in {"fixture", "demo"}:
        return stamp
    return None


def evaluation_date(now: date | None = None) -> date:
    """Production clock is UTC today. Tests/fixtures inject now or STOCK_PM_SYNTHESIS_NOW."""
    if now is not None:
        return now
    injected = _injected_clock()
    if injected is not None:
        return injected
    return utc_today()


def reference_now(chains: list[dict[str, Any]] | None = None, now: date | None = None) -> date:
    del chains
    return evaluation_date(now)


def freshness_state(chain: dict[str, Any], *, now: date) -> dict[str, Any]:
    stamp = _as_date(_period(chain) or chain.get("as_of"))
    if stamp is None:
        return {"fresh": False, "reason": "missing_period", "age_days": None}
    age = (now - stamp).days
    window = freshness_window_days(chain)
    if age < 0:
        return {"fresh": False, "reason": "future", "age_days": age}
    if age > window:
        return {"fresh": False, "reason": "stale", "age_days": age}
    return {"fresh": True, "reason": "fresh", "age_days": age}


def is_fresh(chain: dict[str, Any], *, now: date) -> bool:
    return bool(freshness_state(chain, now=now)["fresh"])


def _complete(chain: dict[str, Any]) -> bool:
    if chain.get("status") != "ok":
        return False
    if not chain_evidence_refs(chain):
        return False
    layers = {row.get("id"): row for row in chain.get("layers") or []}
    if any(name not in layers for name in LAYER_ORDER):
        return False
    return True


def _driver_row(chain: dict[str, Any]) -> dict[str, Any]:
    fact = _layer(chain, "fact")
    change = _layer(chain, "change")
    expectation = _layer(chain, "expectation")
    return {
        "chain_id": chain.get("chain_id"),
        "metric": chain.get("metric"),
        "family": chain.get("family"),
        "theme": _theme(chain),
        "channel_kind": _channel_kind(chain),
        "polarity": polarity(chain),
        "fact_key": fact_key(chain),
        "period": _period(chain),
        "layer": "expectation",
        "layer_id": expectation.get("layer_id") or f"expectation:{chain.get('chain_id')}",
        "cited_layers": [
            {"chain_id": chain.get("chain_id"), "layer": name, "layer_id": (layers := _layer(chain, name)).get("layer_id")}
            for name in ("fact", "change", "expectation")
            if (layers := _layer(chain, name))
        ],
        "fact_text": fact.get("text") or "",
        "change_text": change.get("text") or "",
        "expectation_text": expectation.get("text") or "",
        "evidence_refs": chain_evidence_refs(chain),
    }


def _confidence(
    *,
    independent_facts: int,
    channel_kinds: int,
    confirmed: bool,
    conflict: bool,
    complete: bool,
    fresh: bool,
    duplicates: int,
    vix_only: bool,
    insufficient: bool,
    stale_metrics: list[str] | None = None,
    future_metrics: list[str] | None = None,
) -> dict[str, Any]:
    stale = [item for item in (stale_metrics or []) if item]
    future = [item for item in (future_metrics or []) if item]
    if insufficient or vix_only or independent_facts <= 0:
        label = "insufficient"
        why = "没有足够的独立方向链形成综合判断；VIX 不计入方向票"
    elif conflict:
        label = "limited"
        why = "独立渠道出现反证/信号冲突，按反证降低置信度，不作多数表决或分数平均"
    elif confirmed and independent_facts >= 2 and channel_kinds >= 2 and complete and fresh:
        label = "medium"
        why = (
            f"{independent_facts} 条独立事实、{channel_kinds} 个独立渠道同向确认，"
            f"证据完整且按指标窗口新鲜；同一事实衍生链已去重 {duplicates} 条，VIX 未计入方向"
        )
    elif confirmed and independent_facts >= 2 and channel_kinds >= 2 and complete and not fresh:
        label = "limited"
        bits = []
        if stale:
            bits.append("、".join(stale) + " 超出指标新鲜窗口")
        if future:
            bits.append("、".join(future) + " 为未来日期，不视为新鲜")
        why = (
            f"{independent_facts} 条独立事实已同向确认，但 "
            + ("；".join(bits) or "部分驱动不在有效新鲜窗口")
            + "，置信度低于新鲜同向确认，不作分数平均上修"
        )
    elif confirmed and independent_facts >= 2 and channel_kinds >= 2:
        label = "limited" if not fresh else "medium"
        extra = ""
        if not fresh and future:
            extra = "。关键证据为未来日期，不视为新鲜，置信度低于新鲜确认"
        elif not fresh:
            extra = "。关键证据过期，置信度低于新鲜确认"
        why = (
            f"{independent_facts} 条独立事实、{channel_kinds} 个独立渠道同向确认；禁止把同一事实重复计票（已折叠 {duplicates}）"
            + extra
        )
    elif independent_facts == 1:
        label = "limited"
        why = "仅一条独立方向事实，同一 fact_key 的不同口径不得算作第二渠道确认"
    else:
        label = "limited"
        why = "有多于一条事实但渠道未形成同向确认，也不把票数相加升级"
    if conflict:
        label = "limited"
        if "冲突" not in why:
            why = "同主题内同时存在确认与反证，以冲突为准降低置信度，两侧证据都保留"
    return {
        "label": label,
        "rank": CONFIDENCE_RANK[label],
        "why": why,
        "independent_fact_count": independent_facts,
        "independent_channel_count": channel_kinds,
        "duplicate_facts_collapsed": duplicates,
        "confirmed": confirmed and not conflict,
        "conflict": conflict,
        "complete": complete,
        "fresh": fresh,
        "stale_metrics": stale,
        "future_metrics": future,
        "freshness_policy": "metric_window",
        "clock": "evaluation_date",
        "vix_counted_as_direction": False,
        "majority_vote": False,
        "score_average": False,
    }


def _missing_row(chain: dict[str, Any]) -> dict[str, Any]:
    what = chain.get("what_changes") or {}
    return {
        "chain_id": chain.get("chain_id"),
        "metric": chain.get("metric"),
        "family": chain.get("family"),
        "theme": _theme(chain),
        "reason": chain.get("degrade_reason") or chain.get("status"),
        "detail": chain.get("degrade_detail") or f"{chain.get('metric')} 本链不可用，不作为方向证据",
        "what_changes": what.get("text") or chain.get("degrade_detail") or f"补齐 {chain.get('metric')} 同口径来源后更新本综合判断",
        "evidence_refs": chain_evidence_refs(chain),
    }


def _collapse_by_fact_key(drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in drivers:
        grouped.setdefault(str(row["fact_key"]), []).append(row)
    collapsed: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        polarities = [str(row.get("polarity") or "present") for row in rows]
        if "pressure" in polarities and "relief" in polarities:
            polarity = "mixed"
        else:
            polarity = polarities[0]
        collapsed.append({
            "fact_key": key,
            "polarity": polarity,
            "channel_kind": rows[0].get("channel_kind"),
            "channel_kinds": list(dict.fromkeys(row.get("channel_kind") for row in rows)),
            "rows": rows,
        })
    return collapsed


def _scope_relevance_score(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    target: str | None,
) -> int:
    if scope == "stock" and target:
        return sum(1 for row in rows if chain_relevant_to_stock(row, target))
    if scope == "industry" and target:
        return sum(1 for row in rows if chain_relevant_to_industry(row, target))
    seen: set[str] = set()
    for row in rows:
        for exp in row.get("exposures") or []:
            symbol = str(exp.get("symbol") or "").upper()
            if symbol:
                seen.add(symbol)
    return len(seen)


def _theme_state(
    theme: str,
    chains: list[dict[str, Any]],
    *,
    now: date,
    scope: str = "market",
    target: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in chains if _theme(row) == theme]
    drivers = [_driver_row(row) for row in rows]
    for driver, chain in zip(drivers, rows):
        state = freshness_state(chain, now=now)
        driver["fresh"] = state["fresh"]
        driver["freshness_window_days"] = freshness_window_days(chain)
        driver["freshness_age_days"] = state["age_days"]
        driver["freshness_reason"] = state["reason"]
    collapsed = _collapse_by_fact_key(drivers)
    unique_keys = [row["fact_key"] for row in collapsed]
    duplicates = max(0, len(drivers) - len(unique_keys))
    kinds = list(dict.fromkeys(row["channel_kind"] for row in collapsed))
    by_polarity: dict[str, list[dict[str, Any]]] = {}
    for item in collapsed:
        by_polarity.setdefault(str(item["polarity"] or "present"), []).append(item)
    pressure_facts = by_polarity.get("pressure", [])
    relief_facts = by_polarity.get("relief", [])
    conflict = bool(pressure_facts and relief_facts)
    confirmed = (not conflict) and (len(pressure_facts) >= 2 or len(relief_facts) >= 2)
    net_polarity = None
    if conflict:
        net_polarity = "conflict"
    elif pressure_facts and not relief_facts:
        net_polarity = "pressure"
    elif relief_facts and not pressure_facts:
        net_polarity = "relief"
    elif by_polarity.get("present"):
        net_polarity = "present"
    complete = all(_complete(row) for row in rows) if rows else False
    fresh = all(bool(row.get("fresh")) for row in drivers) if drivers else False
    stale_metrics = sorted({str(row["metric"]) for row in drivers if row.get("freshness_reason") == "stale"})
    future_metrics = sorted({str(row["metric"]) for row in drivers if row.get("freshness_reason") == "future"})
    confirmations = []
    contradictions = []
    if confirmed and net_polarity in {"pressure", "relief"}:
        confirmations.append({
            "theme": theme,
            "text": (
                f"{THEME_LABEL[theme]} 由 "
                + "、".join(sorted({str(row['metric']) for row in drivers}))
                + (" 同向确认利率/折现压力" if theme == "rates" and net_polarity == "pressure"
                   else " 同向确认利率/折现缓和" if theme == "rates"
                   else " 同向确认")
                + "（条件预期，不是已发生事实）"
            ),
            "chain_ids": [row["chain_id"] for row in drivers],
            "evidence_refs": _safe_refs([ref for row in drivers for ref in row["evidence_refs"]]),
        })
    if conflict:
        pressure_metrics = sorted({str(row["metric"]) for item in pressure_facts for row in item["rows"]})
        relief_metrics = sorted({str(row["metric"]) for item in relief_facts for row in item["rows"]})
        contradictions.append({
            "theme": theme,
            "text": (
                f"{'、'.join(relief_metrics)} 与 {'、'.join(pressure_metrics)} 信号冲突，"
                f"置信度低于同向确认情形；两侧证据均保留，不作多数表决"
            ),
            "sides": [
                {"polarity": "pressure", "metrics": pressure_metrics, "chain_ids": [row["chain_id"] for item in pressure_facts for row in item["rows"]]},
                {"polarity": "relief", "metrics": relief_metrics, "chain_ids": [row["chain_id"] for item in relief_facts for row in item["rows"]]},
            ],
            "chain_ids": [row["chain_id"] for row in drivers],
            "evidence_refs": _safe_refs([ref for row in drivers for ref in row["evidence_refs"]]),
        })
    return {
        "theme": theme,
        "label": THEME_LABEL.get(theme, theme),
        "drivers": drivers,
        "confirmations": confirmations,
        "contradictions": contradictions,
        "net_polarity": net_polarity,
        "independent_fact_count": len(unique_keys),
        "independent_channel_count": len(kinds),
        "duplicate_facts_collapsed": duplicates,
        "confirmed": confirmed and not conflict,
        "conflict": conflict,
        "complete": complete,
        "fresh": fresh,
        "stale_metrics": stale_metrics,
        "future_metrics": future_metrics,
        "chain_ids": [row.get("chain_id") for row in rows],
        "scope_relevance": (scope_relevance := _scope_relevance_score(rows, scope=scope, target=target)),
        "scope_relevant": scope_relevance > 0,
    }


def _sort_themes(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    theme_priority = {"rates": 0, "energy": 1, "credit": 2, "geopolitics": 3, "fx": 4}

    def key(row: dict[str, Any]) -> tuple:
        if row["theme"] == "risk":
            return (9, 9, 9, 0, 9)
        status = 0 if row["conflict"] else 1 if row["confirmed"] else 2
        complete = 0 if row["complete"] else 1
        fresh = 0 if row["fresh"] else 1
        relevance = -int(row.get("scope_relevance") or 0)
        return (status, complete, fresh, relevance, theme_priority.get(row["theme"], 5))

    return sorted(states, key=key)


def _select_top_themes(states: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    ranked = _sort_themes(states)
    top = ranked[:limit]
    for row in ranked[limit:]:
        if not row.get("conflict"):
            continue
        if any(item.get("theme") == row["theme"] for item in top):
            continue
        replace_at = next(
            (idx for idx in range(len(top) - 1, -1, -1) if not top[idx]["conflict"] and not top[idx]["confirmed"]),
            None,
        )
        if replace_at is not None:
            top[replace_at] = row
        else:
            top.append(row)
    return top


def _rates_net_text(state: dict[str, Any]) -> tuple[str, str]:
    if state.get("conflict"):
        return (
            "signal_conflict",
            "CPI/就业与 US2Y 等利率渠道信号冲突，置信度低于同向确认；两侧证据均保留（综合条件预期，不是已发生事实）",
        )
    if state.get("net_polarity") == "pressure" and state.get("confirmed"):
        return (
            "rates_discount_pressure",
            "利率/折现压力获独立渠道同向确认（综合条件预期，不是已发生事实；不能形成价格方向）",
        )
    if state.get("net_polarity") == "pressure":
        return (
            "rates_discount_pressure",
            "利率/折现压力仅有有限独立证据（综合条件预期，不是已发生事实）",
        )
    if state.get("net_polarity") == "relief" and state.get("confirmed"):
        return (
            "rates_discount_relief",
            "利率/折现缓和获独立渠道同向确认（综合条件预期，不是已发生事实；不能形成价格方向）",
        )
    if state.get("net_polarity") == "relief":
        return (
            "rates_discount_relief",
            "利率/折现缓和仅有有限独立证据（综合条件预期，不是已发生事实）",
        )
    return ("watch", "利率/折现主题证据不足以下结论，不编造方向")


def _energy_net_text(state: dict[str, Any]) -> tuple[str, str]:
    if state.get("net_polarity") == "pressure":
        return (
            "higher_energy_cost",
            "油价上行先抬升市场通胀与成本预期，再按可验证暴露进入能源生产商收入路径（综合条件预期）",
        )
    if state.get("net_polarity") == "relief":
        return ("lower_energy_cost", "油价回落则通胀/成本链降级（综合条件预期）")
    return ("watch", "能源主题证据不足以下结论")


def _net_for_states(states: list[dict[str, Any]], *, vix_only: bool, missing: list[dict[str, Any]]) -> dict[str, Any]:
    if vix_only or not states:
        missing_bits = "、".join(
            f"{row.get('metric')}（{row.get('reason')}：{row.get('detail')}）" for row in missing[:6]
        ) or "没有 status=ok 的方向链"
        withheld = (
            f"不足以综合利率/折现或能源方向。缺少：{missing_bits}。"
            "补齐上述具体链后更新同一综合判断，不把笼统“数据不足”写成结论。"
        )
        return {
            "stance": "risk_confirmation_only" if vix_only else "withheld",
            "text": (
                "VIX 单独上升只确认风险状态，不形成方向，也不复制到个股。" + withheld
                if vix_only
                else withheld
            ),
            "is_fact": False,
            "kind": "conditional_expectation",
        }
    rates = next((row for row in states if row["theme"] == "rates"), None)
    energy = next((row for row in states if row["theme"] == "energy"), None)
    parts: list[str] = []
    stance = "watch"
    if rates:
        stance, text = _rates_net_text(rates)
        parts.append(text)
    if energy:
        e_stance, e_text = _energy_net_text(energy)
        parts.append(e_text)
        if stance in {"watch", "withheld"}:
            stance = e_stance
    credit = next((row for row in states if row["theme"] == "credit"), None)
    if credit:
        parts.append("信用/融资事件只沿已验证银行暴露传导，无暴露股票不展示（综合条件预期）")
    fx = next((row for row in states if row["theme"] == "fx"), None)
    if fx:
        parts.append("美元代理只在有海外收入折算暴露时进入个股；当前不编造缺失暴露")
    geo = next((row for row in states if row["theme"] == "geopolitics"), None)
    if geo:
        parts.append("地缘/制裁先到市场风险与能源渠道，再按已有暴露映射，不复制到全部股票")
    if not parts:
        parts.append("已观察宏观链不足以形成综合方向，只列出缺失与 What changes")
        stance = "withheld"
    return {
        "stance": stance,
        "text": "；".join(parts),
        "is_fact": False,
        "kind": "conditional_expectation",
    }


def _what_changes(states: list[dict[str, Any]], missing: list[dict[str, Any]], *, vix_only: bool) -> dict[str, Any]:
    follow: list[str] = []
    thresholds: list[str] = []
    texts: list[str] = []
    if vix_only:
        texts.append("出现 CPI/NFP/US2Y 等独立基本面或收益率确认后，才能把风险状态升级为综合方向判断")
        follow.extend(["后续 CPIAUCSL MoM/YoY", "PAYEMS 月差", "DGS2"])
        thresholds.append("至少一条非 VIX 的 status=ok 方向链")
    for state in states:
        if state.get("conflict") and state["theme"] == "rates":
            texts.append("若后续同口径 CPI 与 US2Y 回到同向，则冲突解除并恢复同向确认置信度；任一反向更新同一 chain_id")
            follow.extend(["后续同口径 CPI MoM/YoY", "DGS2 方向"])
            thresholds.append("CPI 与 US2Y 不再反向")
        elif state["theme"] == "rates":
            texts.append("后续同口径通胀/就业回落或 US2Y 反向，则利率/折现综合判断改写，不保留旧结论")
            follow.extend(["后续同口径 CPI", "PAYEMS", "DGS2"])
        elif state["theme"] == "energy":
            texts.append("油价回落或供应恢复则能源综合判断降级；生产商与消费者路径不同")
            follow.append("DCOILWTICO")
        elif state["theme"] == "credit":
            texts.append("财政部/信用文档撤回或拍卖缩量，则信用综合判断失效")
            follow.append("后续官方融资/信用文档")
    for row in missing:
        texts.append(str(row.get("what_changes") or f"补齐 {row.get('metric')} 同口径来源"))
        follow.append(str(row.get("metric") or ""))
    invalidation = (
        "反证或反向更新同一 chain_id 时改写同一 synthesis_id，不并列互相矛盾的旧综合结论。"
        "禁止用 VIX 单独推翻或成立价格方向。"
    )
    text = "；".join(dict.fromkeys(item for item in texts if item)) or "后续官方同口径数据改写本综合判断"
    return {
        "text": text,
        "follow_ups": [item for item in dict.fromkeys(follow) if item],
        "thresholds": [item for item in dict.fromkeys(thresholds) if item],
        "invalidation": invalidation,
    }


def _impact_text(states: list[dict[str, Any]], *, scope: str, target: str | None) -> str:
    bits = ["先到市场"]
    themes = {row["theme"] for row in states}
    if "rates" in themes:
        bits.append("再行业：利率敏感成长 / 半导体久期与银行信用条件")
    if "energy" in themes:
        bits.append("再行业：能源生产收入，不是把油价抄到消费电子")
    if "credit" in themes:
        bits.append("再行业：银行/信用，无暴露不进个股")
    if "fx" in themes:
        bits.append("美元折算仅在有海外收入证据时进入个股")
    bits.append("再按可验证暴露到个股")
    if scope == "stock" and target:
        bits.append(f"本页只保留与 {target} 有已验证暴露的综合链")
    if scope == "industry" and target:
        bits.append(f"本行业卡片只保留 {INDUSTRY_LABELS.get(target, target)}")
    return "，".join(bits)


def _transmission(states: list[dict[str, Any]]) -> dict[str, Any]:
    channels: list[str] = []
    for state in states:
        if state["theme"] == "rates":
            channels.extend(["rates", "discount_rate"])
        elif state["theme"] == "energy":
            channels.append("energy_cost")
        elif state["theme"] == "fx":
            channels.append("fx_translation")
        elif state["theme"] == "credit":
            channels.append("liquidity")
        elif state["theme"] == "geopolitics":
            channels.extend(["risk_aversion", "energy_cost"])
    unique = list(dict.fromkeys(channels))
    return {
        "path": ["market", "industry", "stock"],
        "channels": unique,
        "text": " → ".join(["市场", "行业", "可验证个股暴露"]) + (f"（{' / '.join(unique)}）" if unique else ""),
    }


def _observed_facts(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for chain in chains:
        fact = _layer(chain, "fact")
        if not fact.get("text"):
            continue
        rows.append({
            "kind": "observable_fact",
            "chain_id": chain.get("chain_id"),
            "layer": "fact",
            "layer_id": fact.get("layer_id"),
            "text": fact.get("text"),
            "evidence_refs": chain_evidence_refs(chain),
        })
    return rows


def _derived_rows(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for chain in chains:
        change = _layer(chain, "change")
        if not change.get("text"):
            continue
        rows.append({
            "kind": "derived_analysis",
            "chain_id": chain.get("chain_id"),
            "layer": "change",
            "layer_id": change.get("layer_id"),
            "text": change.get("text"),
            "evidence_refs": chain_evidence_refs(chain),
        })
    return rows


def _vix_block(chains: list[dict[str, Any]], directional: list[dict[str, Any]]) -> dict[str, Any]:
    vix = next((row for row in chains if _is_vix(row) and row.get("status") == "ok"), None)
    if not vix:
        return {
            "role": "risk_confirmation_only",
            "present": False,
            "amplifies": False,
            "sets_direction": False,
            "copied_to_all_stocks": False,
            "text": "当前没有可用 VIX 链；VIX 即使出现也只能确认/放大已有风险，不能单独决定方向",
            "chain_id": None,
            "evidence_refs": [],
        }
    amplifies = bool(directional) and _change_direction(vix) == "up"
    return {
        "role": "risk_confirmation_only",
        "present": True,
        "amplifies": amplifies,
        "sets_direction": False,
        "copied_to_all_stocks": False,
        "text": (
            "VIX 上升确认/放大已有风险状态，不单独形成方向，也不复制到全部个股"
            if amplifies
            else "VIX 只确认风险状态 / 放大其他链，不能单独推导个股涨跌"
        ),
        "chain_id": vix.get("chain_id"),
        "evidence_refs": chain_evidence_refs(vix),
    }


def _synthesis_id(scope: str, target: str | None = None) -> str:
    if scope == "market":
        return "synth:market:macro"
    if scope == "industry":
        return f"synth:industry:{target or 'unknown'}"
    return f"synth:stock:{(target or 'unknown').upper()}"


def _why_stock(symbol: str, chains: list[dict[str, Any]]) -> str:
    reasons = []
    for chain in chains:
        why = chain.get("why_relevant")
        if why:
            reasons.append(str(why))
            continue
        event_type = str(chain.get("event_type") or "")
        if not event_type:
            continue
        stub = TrustedEvent(
            event_id=str(chain.get("event_id") or chain.get("chain_id")),
            canonical_title=str(chain.get("metric") or ""),
            event_type=event_type,
            entities=[],
            countries=[],
            event_time=None,
            published_at=None,
            first_seen_at="",
            updated_at="",
            sources=[],
            claims=[],
            dedupe_group=str(chain.get("chain_id")),
            status="active",
            freshness="fresh",
            severity="medium",
            scope="market",
            duration=None,
            invalidation=None,
        )
        hit = why_relevant(stub, symbol)
        if hit:
            reasons.append(str(hit.get("why_relevant") or ""))
    return "；".join(dict.fromkeys(item for item in reasons if item)) or ""


def _why_industry(industry: str, chains: list[dict[str, Any]]) -> str:
    label = INDUSTRY_LABELS.get(industry, industry)
    metrics = "、".join(sorted({str(row.get("metric") or "") for row in chains if row.get("metric")}))
    return f"{label} 仅纳入已验证渠道（{metrics}），不把市场综合结论机械复制到无关行业"


def _event_type_for(chain: dict[str, Any]) -> str:
    return str(chain.get("event_type") or METRIC_EVENT_TYPE.get(str(chain.get("metric") or "")) or "")


def _stub_event(chain: dict[str, Any]) -> TrustedEvent | None:
    event_type = _event_type_for(chain)
    if not event_type or event_type == "vix_risk":
        return None
    return TrustedEvent(
        event_id=str(chain.get("event_id") or chain.get("chain_id") or event_type),
        canonical_title=str(chain.get("metric") or event_type),
        event_type=event_type,
        entities=[],
        countries=[],
        event_time=None,
        published_at=None,
        first_seen_at="",
        updated_at="",
        sources=[],
        claims=[],
        dedupe_group=str(chain.get("chain_id") or event_type),
        status="active",
        freshness="fresh",
        severity="medium",
        scope="market",
        duration=None,
        invalidation=None,
    )


def chain_relevant_to_stock(chain: dict[str, Any], symbol: str) -> bool:
    wanted = symbol.upper()
    for row in chain.get("exposures") or []:
        if str(row.get("symbol") or "").upper() == wanted:
            return True
    if stock_macro_chains([chain], wanted):
        return True
    stub = _stub_event(chain)
    return bool(stub and why_relevant(stub, wanted))


def chain_relevant_to_industry(chain: dict[str, Any], industry: str) -> bool:
    if industry in _industry_of_chain(chain):
        return True
    return any(chain_relevant_to_stock(chain, symbol) for symbol in INDUSTRY_SYMBOLS.get(industry, ()))


def filter_missing_chains(
    missing_chains: list[dict[str, Any]],
    *,
    scope: str,
    target: str | None = None,
) -> list[dict[str, Any]]:
    rows = [row for row in missing_chains if row.get("status") != "ok"]
    if scope == "market" or not target:
        return rows
    if scope == "stock":
        return [row for row in rows if chain_relevant_to_stock(row, target)]
    if scope == "industry":
        return [row for row in rows if chain_relevant_to_industry(row, target)]
    return []


def _included_chains(chains: list[dict[str, Any]], top: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {chain_id for row in top for chain_id in (row.get("chain_ids") or [])}
    return [row for row in chains if row.get("chain_id") in wanted]


def impact_stocks(scope: str, target: str | None, chains: list[dict[str, Any]]) -> list[str]:
    if scope == "stock" and target:
        return [target.upper()]
    symbols: list[str] = []
    for chain in chains:
        for row in chain.get("exposures") or []:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            channel = str(row.get("channel") or "")
            if scope == "industry" and target:
                allowed = INDUSTRY_CHANNELS.get(target, frozenset())
                if channel and channel not in allowed:
                    continue
                if symbol not in INDUSTRY_SYMBOLS.get(target, ()):
                    continue
            symbols.append(symbol)
    return list(dict.fromkeys(symbols))


def _impact_industries(scope: str, target: str | None, chains: list[dict[str, Any]]) -> list[str]:
    if scope == "industry" and target:
        return [target]
    found: list[str] = []
    wanted = target.upper() if scope == "stock" and target else None
    for chain in chains:
        if wanted:
            channels = {
                str(row.get("channel") or "")
                for row in (chain.get("exposures") or [])
                if str(row.get("symbol") or "").upper() == wanted
            }
            for industry, allowed in INDUSTRY_CHANNELS.items():
                if channels & allowed:
                    found.append(industry)
            continue
        for industry in sorted(_industry_of_chain(chain)):
            found.append(industry)
    return list(dict.fromkeys(found))


def build_scope_synthesis(
    chains: list[dict[str, Any]],
    *,
    scope: str,
    target: str | None = None,
    missing_chains: list[dict[str, Any]] | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    ok = [row for row in chains if row.get("status") == "ok"]
    directional = [row for row in ok if _is_directional_ok(row)]
    vix_ok = [row for row in ok if _is_vix(row)]
    scoped_missing_src = filter_missing_chains(list(missing_chains or []), scope=scope, target=target)
    missing = [_missing_row(row) for row in scoped_missing_src]
    clock = evaluation_date(now)
    theme_names = list(dict.fromkeys(_theme(row) for row in directional))
    states = [
        _theme_state(name, directional, now=clock, scope=scope, target=target)
        for name in theme_names
        if name in DIRECTIONAL_THEMES
    ]
    top = _select_top_themes(states)
    included = _included_chains(directional, top)
    vix_only = bool(vix_ok) and not directional
    insufficient = not directional
    net = _net_for_states(top, vix_only=vix_only, missing=missing)
    stale_metrics = sorted({metric for row in top for metric in row.get("stale_metrics") or []})
    future_metrics = sorted({metric for row in top for metric in row.get("future_metrics") or []})
    if top:
        lead = top[0]
        confidence = _confidence(
            independent_facts=lead["independent_fact_count"] if lead["theme"] == "rates" else sum(row["independent_fact_count"] for row in top),
            channel_kinds=lead["independent_channel_count"] if lead["theme"] == "rates" else len({kind for row in top for kind in {d["channel_kind"] for d in row["drivers"]}}),
            confirmed=lead["confirmed"] if lead["theme"] == "rates" else any(row["confirmed"] for row in top) and not any(row["conflict"] for row in top),
            conflict=lead["conflict"] if lead["theme"] == "rates" else any(row["conflict"] for row in top),
            complete=lead["complete"] if lead["theme"] == "rates" else all(row["complete"] for row in top),
            fresh=lead["fresh"] if lead["theme"] == "rates" else all(row["fresh"] for row in top),
            duplicates=lead["duplicate_facts_collapsed"] if lead["theme"] == "rates" else sum(row["duplicate_facts_collapsed"] for row in top),
            vix_only=False if top else vix_only,
            insufficient=insufficient,
            stale_metrics=lead.get("stale_metrics") if lead["theme"] == "rates" else stale_metrics,
            future_metrics=lead.get("future_metrics") if lead["theme"] == "rates" else future_metrics,
        )
    else:
        confidence = _confidence(
            independent_facts=0,
            channel_kinds=0,
            confirmed=False,
            conflict=False,
            complete=False,
            fresh=False,
            duplicates=0,
            vix_only=vix_only,
            insufficient=True,
        )
    as_of = clock.isoformat()
    why = ""
    if scope == "stock" and target:
        why = _why_stock(target, directional)
    elif scope == "industry" and target:
        why = _why_industry(target, directional)
    refs = _safe_refs([ref for row in directional + vix_ok for ref in chain_evidence_refs(row)])
    stocks = impact_stocks(scope, target, included)
    return {
        "synthesis_id": _synthesis_id(scope, target),
        "scope": scope,
        "target": target,
        "as_of": as_of,
        "drivers": [item for row in top for item in row["drivers"]],
        "driver_themes": [
            {
                "theme": row["theme"],
                "label": row["label"],
                "net_polarity": row["net_polarity"],
                "confirmed": row["confirmed"],
                "conflict": row["conflict"],
                "independent_fact_count": row["independent_fact_count"],
                "chain_ids": row["chain_ids"],
                "fresh": row["fresh"],
                "stale_metrics": row.get("stale_metrics") or [],
                "future_metrics": row.get("future_metrics") or [],
                "scope_relevance": row.get("scope_relevance") or 0,
            }
            for row in top
        ],
        "confirmations": [item for row in top for item in row["confirmations"]],
        "contradictions": [item for row in top for item in row["contradictions"]],
        "net_expectation": net,
        "transmission": _transmission(top),
        "impact": {
            "text": _impact_text(top, scope=scope, target=target),
            "markets": [row["theme"] for row in top if row["theme"] in {"rates", "energy", "fx", "credit"}],
            "industries": _impact_industries(scope, target, included),
            "stocks": stocks,
        },
        "confidence": confidence,
        "evidence_refs": refs,
        "what_changes": _what_changes(top, missing, vix_only=vix_only),
        "can_form_direction": False,
        "percent_forecast": None,
        "price_target": None,
        "observed_facts": _observed_facts(ok if scope == "market" else directional),
        "derived_analysis": _derived_rows(ok if scope == "market" else directional),
        "missing": missing,
        "vix": _vix_block(ok, directional),
        "why_relevant": why,
        "kind": "synthesis_conditional_expectation",
    }


def _industry_of_chain(chain: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for row in chain.get("exposures") or []:
        channel = str(row.get("channel") or "")
        for industry, channels in INDUSTRY_CHANNELS.items():
            if channel in channels:
                found.add(industry)
    return found


def synthesize_drivers(
    chains: list[dict[str, Any]],
    *,
    symbols: list[str] | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    wanted = [item.upper() for item in (symbols or SYNTHESIS_SYMBOLS)]
    missing_src = [row for row in chains if row.get("status") != "ok"]
    clock = evaluation_date(now)
    vix_ok = [row for row in chains if _is_vix(row)]
    market = build_scope_synthesis(chains, scope="market", missing_chains=missing_src, now=clock)
    industries: list[dict[str, Any]] = []
    for industry in ("semis", "energy", "banks"):
        mapped = [
            row for row in chains
            if row.get("status") == "ok" and not _is_vix(row) and industry in _industry_of_chain(row)
        ]
        if not mapped:
            continue
        industries.append(
            build_scope_synthesis(
                [*mapped, *vix_ok],
                scope="industry",
                target=industry,
                missing_chains=missing_src,
                now=clock,
            )
        )
    stocks: dict[str, dict[str, Any]] = {}
    for symbol in wanted:
        mapped = [row for row in stock_macro_chains(chains, symbol) if row.get("status") == "ok"]
        if not mapped:
            continue
        stocks[symbol] = build_scope_synthesis(
            [*mapped, *vix_ok],
            scope="stock",
            target=symbol,
            missing_chains=missing_src,
            now=clock,
        )
    return {
        "market": market,
        "industries": industries,
        "stocks": stocks,
        "syntheses": [market, *industries, *stocks.values()],
        "note": "综合判断是条件预期，区别于已观察事实和单链派生分析。VIX 不单独决定方向。",
    }


def stock_synthesis(chains: list[dict[str, Any]], symbol: str, *, now: date | None = None) -> dict[str, Any] | None:
    payload = synthesize_drivers(chains, symbols=[symbol], now=now)
    return payload["stocks"].get(symbol.upper())


def summarize_synthesis(payload: dict[str, Any]) -> dict[str, Any]:
    market = payload.get("market") or {}
    net = market.get("net_expectation") or {}
    confidence = market.get("confidence") or {}
    return {
        "synthesis_id": market.get("synthesis_id"),
        "scope": "market",
        "stance": net.get("stance"),
        "text": net.get("text"),
        "confidence": confidence.get("label"),
        "confidence_why": confidence.get("why"),
        "conflict": bool((market.get("contradictions") or []) or confidence.get("conflict")),
        "driver_count": len(market.get("driver_themes") or []),
        "can_form_direction": False,
        "vix_role": (market.get("vix") or {}).get("role"),
        "missing_metrics": [row.get("metric") for row in market.get("missing") or []],
        "note": payload.get("note"),
    }
