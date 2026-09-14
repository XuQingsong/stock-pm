"""Market-level Macro Causal Chain. Structured rules only. No LLM narrative.

Reuses event analysis layers and selective exposure. Production never loads
the frozen 6A pack; fixture/test modes are labeled frozen_provider_audit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from stock_pm.decision.causal import canonical_metric
from stock_pm.decision.inject import inject_allowed
from stock_pm.nfp import NFP_FORMULA

from .exposure import attach_exposures, why_relevant
from .policy import events_data_mode
from .types import TrustedEvent


FROZEN_6A_PATH = Path(__file__).resolve().parent.parent / "data" / "events_6a_frozen_macro.json"
FROZEN_NOTE = "Frozen/fixture macro facts are not production live coverage."

LAYER_ORDER = ("fact", "change", "expectation", "transmission", "impact", "what_changes")
LAYER_KINDS = {
    "fact": "observable_fact",
    "change": "derived_analysis",
    "expectation": "conditional_expectation",
    "transmission": "derived_analysis",
    "impact": "derived_analysis",
    "what_changes": "derived_analysis",
}

TRANSMISSION_CHANNELS = (
    "rates",
    "discount_rate",
    "growth",
    "liquidity",
    "risk_aversion",
    "energy_cost",
    "fx_translation",
)

METRIC_FAMILY = {
    "cpi": "inflation",
    "core_cpi": "inflation",
    "nfp": "labor",
    "us2y": "rates",
    "vix": "risk",
    "wti": "energy",
    "oil": "energy",
    "gold": "commodity",
    "broad_usd_proxy": "fx",
}

EVENT_FAMILY = {
    "inflation_employment": "inflation",
    "central_bank_rates": "rates",
    "vix_risk": "risk",
    "energy_supply": "energy",
    "gold_wti": "energy",
    "war_sanctions": "geopolitics",
    "sovereign_or_corporate_debt": "credit",
    "fx_usd": "fx",
}

INJECT_KEYS = frozenset({
    "missing_cpi_baseline",
    "period_mismatch_nfp",
    "source_fail_us2y",
    "reverse_cpi",
})

_CACHE: dict[str, Any] = {"facts": None, "chains": None}


def reset_macro_cache() -> None:
    _CACHE["facts"] = None
    _CACHE["chains"] = None


def stable_chain_id(family: str, metric: str, period: str) -> str:
    return f"macro:{family}:{metric}:{period}"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _period_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unspecified"
    return text[:10]


def _ref(fact: dict[str, Any] | None, *, source_id: str | None = None) -> dict[str, Any]:
    row = fact or {}
    url = str(row.get("http_source") or row.get("source_url") or "")
    return {
        "source_id": source_id or f"macro:{row.get('metric') or 'unknown'}:{_period_key(row.get('period') or row.get('as_of'))}",
        "source_url": url,
        "publisher": str(row.get("source") or row.get("publisher") or ""),
        "source_tier": 1 if url.startswith("http") else 0,
        "content_type": "official_fact",
        "fact_or_opinion": "fact",
        "as_of": row.get("as_of") or row.get("period"),
        "series": row.get("series") or row.get("series_or_symbol"),
    }


def _layer(chain_id: str, name: str, text: str, refs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "id": name,
        "layer_id": f"{name}:{chain_id}",
        "layer_kind": LAYER_KINDS[name],
        "text": text or "",
        "cites": [f"{LAYER_ORDER[LAYER_ORDER.index(name) - 1]}:{chain_id}"] if name != "fact" else [],
        "evidence_refs": list(refs),
        **extra,
    }


def compare_same_basis(fact: dict[str, Any]) -> dict[str, Any]:
    """Same-unit / same-definition comparison. Never mix level vs change or periods."""
    metric = canonical_metric(str(fact.get("metric") or ""))
    actual = _num(fact.get("actual") if fact.get("actual") is not None else fact.get("value"))
    prior = _num(fact.get("prior"))
    consensus = _num(fact.get("consensus"))
    unit = str(fact.get("unit") or "")
    series = str(fact.get("series") or fact.get("series_or_symbol") or "")
    period = _period_key(fact.get("period") or fact.get("as_of"))
    prior_as_of = _period_key(fact.get("prior_as_of"))
    consensus_period = _period_key(fact.get("consensus_as_of") or fact.get("consensus_period"))
    actual_basis = str(fact.get("basis") or fact.get("comparison") or "")
    prior_basis = str(fact.get("prior_basis") or "")
    consensus_unit = str(fact.get("consensus_unit") or unit)
    prior_unit = str(fact.get("prior_unit") or unit)
    status = "ok"
    reason = ""
    baseline = None
    baseline_kind = None
    if str(fact.get("status") or "ok") in {"error", "invalid", "missing", "unavailable"}:
        return {
            "status": "degraded",
            "reason": "source_failed",
            "detail": f"{metric} 来源失败（{fact.get('status')} / {fact.get('reason_code') or 'source_failed'}），只降级本链",
            "actual": actual,
            "baseline": None,
            "delta": None,
            "direction": None,
        }
    if actual is None:
        return {
            "status": "degraded",
            "reason": "missing_actual",
            "detail": f"{metric} 缺少可观察实际值，只降级本链",
            "actual": None,
            "baseline": None,
            "delta": None,
            "direction": None,
        }
    if metric == "nfp" and (
        prior_basis in {"level", "employment_stock"}
        or actual_basis in {"level", "employment_stock"}
        or (prior is not None and abs(prior) > abs(actual) * 20)
    ):
        return {
            "status": "degraded",
            "reason": "period_or_basis_mismatch",
            "detail": "NFP 不得把就业存量与月度差分比较；只降级本劳动链",
            "actual": actual,
            "baseline": prior,
            "delta": None,
            "direction": None,
            "formula": NFP_FORMULA,
        }
    if consensus is not None and consensus_unit and unit and consensus_unit != unit:
        return {
            "status": "degraded",
            "reason": "period_or_basis_mismatch",
            "detail": f"{metric} 共识单位 {consensus_unit} 与实际单位 {unit} 不一致，只降级本链",
            "actual": actual,
            "baseline": consensus,
            "delta": None,
            "direction": None,
        }
    if consensus is not None and consensus_period not in {"", "unspecified"} and consensus_period != period:
        return {
            "status": "degraded",
            "reason": "period_or_basis_mismatch",
            "detail": f"{metric} 共识期次 {consensus_period} 与实际期次 {period} 不一致，只降级本链",
            "actual": actual,
            "baseline": consensus,
            "delta": None,
            "direction": None,
        }
    if prior is not None and prior_unit and unit and prior_unit != unit:
        return {
            "status": "degraded",
            "reason": "period_or_basis_mismatch",
            "detail": f"{metric} 前值单位 {prior_unit} 与实际单位 {unit} 不一致，只降级本链",
            "actual": actual,
            "baseline": prior,
            "delta": None,
            "direction": None,
        }
    if consensus is not None:
        baseline = consensus
        baseline_kind = "consensus"
        formula = fact.get("formula") or f"{series or metric} actual vs consensus ({unit})"
    elif prior is not None:
        baseline = prior
        baseline_kind = "prior"
        formula = fact.get("formula") or f"{series or metric}[t] vs {series or metric}[t−1] ({unit})"
    else:
        return {
            "status": "degraded",
            "reason": "missing_baseline",
            "detail": f"{metric} 缺少同口径前值或一致预期，不能声称变化，只降级本链",
            "actual": actual,
            "baseline": None,
            "delta": None,
            "direction": None,
        }
    delta = actual - baseline
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "unchanged"
    return {
        "status": status,
        "reason": reason,
        "actual": actual,
        "baseline": baseline,
        "baseline_kind": baseline_kind,
        "delta": delta,
        "direction": direction,
        "unit": unit,
        "series": series,
        "period": period,
        "prior_as_of": prior_as_of if prior is not None else None,
        "consensus_period": consensus_period if consensus is not None else None,
        "formula": formula,
        "comparison": fact.get("comparison") or "same_series_same_unit",
    }


def _expectation_for(metric: str, change: dict[str, Any]) -> dict[str, Any]:
    direction = change.get("direction")
    kind = change.get("baseline_kind")
    if metric == "cpi" and direction == "up" and kind == "consensus":
        return {
            "text": "通胀高于一致预期 → 降息预期后移（条件预期，不是已发生事实）",
            "stance": "cut_odds_delayed",
            "confidence": "medium",
        }
    if metric == "cpi" and direction == "up":
        return {
            "text": "通胀环比上升；若持续，降息预期可能后移（条件预期；无一致预期，不是 street surprise）",
            "stance": "cut_odds_delayed_conditional",
            "confidence": "limited",
        }
    if metric == "cpi" and direction == "down":
        return {
            "text": "通胀低于比较基准 → 降息预期可能前移（条件预期，不是已发生事实）",
            "stance": "cut_odds_earlier",
            "confidence": "medium" if kind == "consensus" else "limited",
        }
    if metric == "nfp" and direction == "up":
        return {
            "text": "同口径就业韧性强于比较基准 → 降息预期后移（条件预期，不是已发生事实）",
            "stance": "cut_odds_delayed",
            "confidence": "medium" if kind == "consensus" else "limited",
        }
    if metric == "nfp" and direction == "down":
        return {
            "text": "同口径就业弱于比较基准 → 降息预期可能前移（条件预期，不是已发生事实）",
            "stance": "cut_odds_earlier",
            "confidence": "medium" if kind == "consensus" else "limited",
        }
    if metric == "us2y" and direction == "up":
        return {
            "text": "两年期收益率上升，确认折现率上行压力（条件预期）",
            "stance": "higher_discount",
            "confidence": "medium",
        }
    if metric == "vix":
        return {
            "text": "VIX 只确认风险状态 / 放大其他链，不单独推导个股涨跌",
            "stance": "risk_confirmation_only",
            "confidence": "high" if direction == "up" else "limited",
        }
    if metric in {"wti", "oil"} and direction == "up":
        return {
            "text": "油价上行先抬升市场通胀与成本预期，再按暴露进入行业（条件预期）",
            "stance": "higher_energy_cost",
            "confidence": "medium",
        }
    if metric == "broad_usd_proxy" and direction == "up":
        return {
            "text": "美元代理走强，可能通过汇率折算影响海外收入（条件预期；无暴露则不进个股）",
            "stance": "stronger_usd",
            "confidence": "limited",
        }
    return {
        "text": "证据只支持观察，不把规则外推成确定事实",
        "stance": "watch",
        "confidence": "limited",
    }


def _transmission_for(metric: str, family: str) -> list[str]:
    if metric in {"cpi", "core_cpi", "nfp", "us2y"} or family in {"inflation", "labor", "rates"}:
        return ["rates", "discount_rate"]
    if metric == "vix" or family == "risk":
        return ["risk_aversion"]
    if metric in {"wti", "oil"} or family == "energy":
        return ["energy_cost"]
    if family == "geopolitics":
        return ["risk_aversion", "energy_cost"]
    if family == "credit":
        return ["liquidity"]
    if family == "fx" or metric == "broad_usd_proxy":
        return ["fx_translation"]
    return []


def _market_impact(metric: str, change: dict[str, Any], expectation: dict[str, Any]) -> str:
    if metric in {"cpi", "nfp"} and expectation.get("stance") in {"cut_odds_delayed", "cut_odds_delayed_conditional"}:
        return "先市场：高估值成长风格承压；再行业：利率敏感成长 / 半导体久期"
    if metric == "vix":
        return "先市场：风险偏好下降的确认/放大；不形成个股涨跌"
    if metric in {"wti", "oil"}:
        return "先市场：通胀与成本；再行业：能源生产、运输、能源敏感消费"
    if metric == "us2y":
        return "先市场：折现率；再行业：高估值成长"
    if metric == "broad_usd_proxy":
        return "先市场：美元流动性/折算；无收入地域证据则不进个股"
    return "先市场/资产风格，再按已有暴露进入行业"


def _what_changes(metric: str, change: dict[str, Any]) -> dict[str, Any]:
    if metric == "cpi":
        return {
            "text": "后续通胀回落或 US2Y 反向，则降息后移/成长承压判断失效",
            "follow_ups": ["后续 CPI 公布", "US2Y 方向反转", "FOMC 沟通"],
            "thresholds": ["CPI 相对同一口径共识/前值转负", "DGS2 不再走高"],
            "invalidation": "若后续通胀回落且收益率反向，则本链条件预期失效",
        }
    if metric == "nfp":
        return {
            "text": "后续同口径 ΔPAYEMS 回落或失业率反向，则就业韧性/降息后移判断失效",
            "follow_ups": ["下一份 PAYEMS 月差", "失业率"],
            "thresholds": ["同口径月差转弱"],
            "invalidation": "不得用就业存量推翻月差结论；下一份同口径差分改写本链",
        }
    if metric == "vix":
        return {
            "text": "VIX 回落到阈值内且没有其他基本面/收益率确认时，风险放大解除",
            "follow_ups": ["VIXCLS", "US2Y", "盈利/通胀反证"],
            "thresholds": ["VIX 回落且无独立基本面恶化"],
            "invalidation": "禁止把 VIX 升跌直接写成某只股票的涨跌方向",
        }
    if metric in {"wti", "oil"}:
        return {
            "text": "油价回落或供应恢复，则通胀/成本链降级；生产商与消费者路径不同",
            "follow_ups": ["WTI", "EIA 供应"],
            "thresholds": ["油价相对前值转负"],
            "invalidation": "供应恢复或价格回撤则成本冲击失效",
        }
    if metric == "us2y":
        return {
            "text": "收益率回落则折现率压力解除",
            "follow_ups": ["DGS2"],
            "thresholds": ["US2Y 相对前值转负"],
            "invalidation": "收益率反向则本确认失效",
        }
    return {
        "text": "后续官方同口径数据改写本链，不新建互相矛盾的平行事件",
        "follow_ups": [],
        "thresholds": [],
        "invalidation": "反证出现时更新同一 stable chain",
    }


def _counter_evidence(metric: str, facts: list[dict[str, Any]], change: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_metric = {canonical_metric(str(row.get("metric") or row.get("event_type") or "")): row for row in facts}
    if metric == "vix":
        us2y = compare_same_basis(by_metric["us2y"]) if "us2y" in by_metric else None
        cpi = compare_same_basis(by_metric["cpi"]) if "cpi" in by_metric else None
        if us2y and us2y.get("status") == "ok" and us2y.get("direction") == "down" and change.get("direction") == "up":
            rows.append({
                "text": "VIX 上升但 US2Y 下行，收益率未确认风险-折现同向；VIX 只作风险确认",
                "evidence_refs": [_ref(by_metric["us2y"])],
            })
        if cpi and cpi.get("status") == "ok" and cpi.get("direction") == "down" and change.get("direction") == "up":
            rows.append({
                "text": "VIX 上升但 CPI 回落，基本面未确认风险溢价为定价方向",
                "evidence_refs": [_ref(by_metric["cpi"])],
            })
        if not rows:
            rows.append({
                "text": "即使没有反向序列，VIX 也不能单独推导 AAPL/NVDA 跌幅",
                "evidence_refs": [_ref(by_metric.get("vix"))],
            })
    return rows


def _unavailable(metric: str, family: str, reason: str, detail: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    period = "unavailable"
    chain_id = stable_chain_id(family, metric, period)
    return {
        "chain_id": chain_id,
        "family": family,
        "metric": metric,
        "status": "unavailable" if reason in {"missing_actual", "source_failed"} and "actual" in detail else "degraded",
        "degrade_reason": reason,
        "degrade_detail": detail,
        "data_class": "unavailable",
        "live": False,
        "can_form_direction": False,
        "percent_forecast": None,
        "price_target": None,
        "vix_role": "risk_confirmation_only" if metric == "vix" else "not_applicable",
        "layers": [
            _layer(chain_id, "fact", detail, refs, excerpt=""),
            _layer(chain_id, "change", "", refs, status="degraded", reason=reason),
            _layer(chain_id, "expectation", "本链条件预期未形成，不输出方向预测", refs, stance="withheld", confidence="insufficient"),
            _layer(chain_id, "transmission", "", refs, channels=[]),
            _layer(chain_id, "impact", "本链降级，不影响其他健康宏观链", refs, exposures=[], markets=[]),
            _layer(chain_id, "what_changes", "补齐同口径基线/来源后更新同一 chain_id，不笼统写数据不足", refs),
        ],
        "counter_evidence": [{"text": detail, "evidence_refs": refs}],
        "what_changes": {"text": detail, "follow_ups": [], "thresholds": [], "invalidation": detail},
        "exposures": [],
    }


def build_numeric_macro_chain(
    fact: dict[str, Any],
    *,
    companion_facts: list[dict[str, Any]] | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    metric = canonical_metric(str(fact.get("metric") or fact.get("event_type") or ""))
    family = METRIC_FAMILY.get(metric, "other")
    refs = [_ref(fact)]
    change = compare_same_basis(fact)
    data_class = str(fact.get("data_class") or "live_current")
    live = data_class == "live_current" and str(fact.get("status") or "ok") == "ok"
    if change.get("status") != "ok":
        row = _unavailable(metric, family, str(change.get("reason") or "missing_baseline"), str(change.get("detail") or ""), refs)
        row["data_class"] = data_class
        row["live"] = False
        row["period"] = _period_key(fact.get("period") or fact.get("as_of"))
        row["chain_id"] = stable_chain_id(family, metric, row["period"])
        for layer in row["layers"]:
            layer["layer_id"] = f"{layer['id']}:{row['chain_id']}"
            if layer["id"] != "fact":
                layer["cites"] = [f"{LAYER_ORDER[LAYER_ORDER.index(layer['id']) - 1]}:{row['chain_id']}"]
        return row
    period = str(change.get("period") or _period_key(fact.get("period") or fact.get("as_of")))
    chain_id = stable_chain_id(family, metric, period)
    expectation = _expectation_for(metric, change)
    channels = [item for item in _transmission_for(metric, family) if item in TRANSMISSION_CHANNELS]
    what = _what_changes(metric, change)
    fact_text = (
        f"{fact.get('name') or metric.upper()} 实际值 {change['actual']} {change.get('unit') or ''} "
        f"· 期间 {period} · 来源 {fact.get('source') or '—'} · as_of {fact.get('as_of') or period} "
        f"· 序列 {change.get('series') or '—'}"
    )
    change_text = (
        f"相对{('一致预期' if change.get('baseline_kind') == 'consensus' else '同口径前值')} "
        f"{change['baseline']} {change.get('unit') or ''}，Δ {change['delta']:+g} "
        f"（{change.get('formula')}）"
    )
    event_type = {
        "cpi": "inflation_employment",
        "nfp": "inflation_employment",
        "us2y": "central_bank_rates",
        "vix": "vix_risk",
        "wti": "energy_supply",
        "oil": "energy_supply",
        "gold": "gold_wti",
        "broad_usd_proxy": "fx_usd",
    }.get(metric, "other")
    stub = TrustedEvent(
        event_id=chain_id,
        canonical_title=str(fact.get("name") or metric),
        event_type=event_type,
        entities=[],
        countries=[],
        event_time=str(fact.get("as_of") or ""),
        published_at=str(fact.get("as_of") or ""),
        first_seen_at=str(fact.get("as_of") or ""),
        updated_at=str(fact.get("as_of") or ""),
        sources=[],
        claims=[],
        dedupe_group=chain_id,
        status="active",
        freshness="fresh",
        severity="medium",
        scope="market",
        duration=None,
        invalidation=what.get("invalidation"),
    )
    wanted = [item.upper() for item in (symbols or ("NVDA", "XOM", "JPM", "AAPL", "NOK"))]
    exposures = [] if metric == "vix" else attach_exposures(stub, wanted)
    impact_text = _market_impact(metric, change, expectation)
    if exposures:
        impact_text += "".join(
            f"；{row.get('symbol')} 经 {row.get('channel')}（{row.get('mechanism')}）" for row in exposures
        )
    elif metric != "vix":
        impact_text += "。无已验证暴露的股票不展示个股影响"
    layers = [
        _layer(chain_id, "fact", fact_text, refs, excerpt=str(fact.get("formula") or ""), value=change["actual"], unit=change.get("unit"), as_of=fact.get("as_of") or period, source=fact.get("source")),
        _layer(chain_id, "change", change_text, refs, **{k: change[k] for k in ("delta", "direction", "baseline", "baseline_kind", "formula") if k in change}),
        _layer(chain_id, "expectation", expectation["text"], refs, stance=expectation["stance"], confidence=expectation["confidence"], is_fact=False),
        _layer(chain_id, "transmission", " / ".join(channels), refs, channels=channels),
        _layer(chain_id, "impact", impact_text, refs, exposures=exposures, markets=channels),
        _layer(chain_id, "what_changes", what["text"], refs, follow_ups=what["follow_ups"], thresholds=what["thresholds"], invalidation=what["invalidation"]),
    ]
    return {
        "chain_id": chain_id,
        "family": family,
        "metric": metric,
        "event_type": event_type,
        "period": period,
        "status": "ok",
        "degrade_reason": None,
        "degrade_detail": None,
        "data_class": data_class,
        "live": live,
        "can_form_direction": False,
        "percent_forecast": None,
        "price_target": None,
        "vix_role": "risk_confirmation_only" if metric == "vix" else "not_applicable",
        "layers": layers,
        "counter_evidence": _counter_evidence(metric, list(companion_facts or []) + [fact], change),
        "what_changes": what,
        "exposures": exposures,
        "confidence": expectation["confidence"],
        "event_id": chain_id,
    }


def build_event_macro_chain(event: TrustedEvent, analysis: dict[str, Any]) -> dict[str, Any] | None:
    """One market-level chain per trusted event. Stock pages cite this chain_id."""
    if event.event_type in {"company_earnings", "company_filing"}:
        return None
    family = EVENT_FAMILY.get(event.event_type)
    if not family:
        return None
    metric = {
        "inflation_employment": "inflation_employment",
        "central_bank_rates": "policy_rate",
        "vix_risk": "vix",
        "energy_supply": "energy_supply",
        "gold_wti": "wti",
        "war_sanctions": "war_sanctions",
        "sovereign_or_corporate_debt": "credit",
        "fx_usd": "broad_usd_proxy",
    }.get(event.event_type, event.event_type)
    period = _period_key(event.event_time or event.published_at or event.updated_at or event.event_id)
    chain_id = stable_chain_id(family, metric, period)
    refs = list((analysis.get("evidence_refs") or [])[:3])
    fact_text = str(((analysis.get("confirmed_facts") or [{}])[0] or {}).get("text") or event.canonical_title)
    change_item = analysis.get("change_vs_baseline") or {}
    change_text = change_item.get("text") if isinstance(change_item, dict) else str(change_item or "")
    what_item = analysis.get("what_changes") or {}
    what_text = what_item.get("text") if isinstance(what_item, dict) else str(what_item or "")
    channels = _transmission_for(metric if metric != "inflation_employment" else "cpi", family)
    exposures = list(analysis.get("exposures") or [])
    if event.event_type == "vix_risk":
        exposures = []
    impact_text = "先市场级风险与传导，再按已有暴露映射"
    if event.event_type == "war_sanctions":
        impact_text = "先市场级风险与能源/供应链渠道，再按暴露映射；不复制到全部股票"
    elif event.event_type == "energy_supply":
        impact_text = "先市场通胀/成本，再选择性影响能源、运输、消费"
    elif event.event_type == "sovereign_or_corporate_debt":
        impact_text = "通过信用利差/融资/流动性渠道；没有暴露证据不进个股"
    if exposures:
        impact_text += "".join(
            f"；{row.get('symbol')} 经 {row.get('channel')}（{row.get('mechanism')}）" for row in exposures
        )
    expectation_text = str((analysis.get("mechanism") or {}).get("text") or "条件预期未升级为确定事实")
    if event.event_type == "vix_risk":
        expectation_text = "VIX 只确认风险 / 放大其他链，不能单独推导个股涨跌"
    invalidation = str((analysis.get("invalidation") or {}).get("text") or event.invalidation or "")
    layers = [
        _layer(chain_id, "fact", fact_text, refs, excerpt=str(((analysis.get("causal_chain") or {}).get("layers") or [{}])[0].get("excerpt") if (analysis.get("causal_chain") or {}).get("layers") else "")),
        _layer(chain_id, "change", change_text or "", refs or change_item.get("evidence_refs") or []),
        _layer(chain_id, "expectation", expectation_text, refs, stance="conditional", confidence=str((analysis.get("confidence") or {}).get("text") or "limited"), is_fact=False),
        _layer(chain_id, "transmission", " / ".join(channels), refs, channels=channels),
        _layer(chain_id, "impact", impact_text, refs, exposures=exposures, markets=channels),
        _layer(chain_id, "what_changes", what_text or invalidation, refs, invalidation=invalidation, follow_ups=["后续官方文档"], thresholds=[]),
    ]
    missing = []
    if not str(change_text or "").strip():
        missing.append("missing_baseline")
    status = "degraded" if missing else "ok"
    return {
        "chain_id": chain_id,
        "family": family,
        "metric": metric,
        "event_type": event.event_type,
        "event_id": event.event_id,
        "period": period,
        "status": status,
        "degrade_reason": missing[0] if missing else None,
        "degrade_detail": "缺少可比较基线，只降级本事件链" if missing else None,
        "data_class": "event_document",
        "live": None,
        "can_form_direction": False if event.event_type == "vix_risk" else analysis.get("can_form_direction"),
        "percent_forecast": None,
        "price_target": None,
        "vix_role": "risk_confirmation_only" if event.event_type == "vix_risk" else "not_applicable",
        "layers": layers,
        "counter_evidence": list(analysis.get("counter_evidence") or []),
        "what_changes": {
            "text": what_text or invalidation,
            "follow_ups": ["后续官方文档"],
            "thresholds": [],
            "invalidation": invalidation,
        },
        "exposures": exposures,
        "confidence": str((analysis.get("confidence") or {}).get("text") or ""),
    }


def attach_event_macro_chain(event: TrustedEvent, analysis: dict[str, Any]) -> dict[str, Any]:
    payload = dict(analysis)
    chain = build_event_macro_chain(event, payload)
    if chain:
        payload["macro_chain"] = chain
        payload["macro_chain_id"] = chain["chain_id"]
    return payload


def fact_from_fred_row(row: dict[str, Any], *, data_class: str = "live_current") -> dict[str, Any]:
    metric = canonical_metric(str(row.get("event_type") or row.get("metric") or ""))
    return {
        "metric": metric,
        "name": row.get("name") or metric.upper(),
        "actual": row.get("actual") if row.get("actual") is not None else row.get("value"),
        "prior": row.get("prior"),
        "consensus": row.get("consensus") if row.get("consensus") not in {None, "", "unknown"} else None,
        "unit": row.get("unit"),
        "series": row.get("series") or row.get("series_or_symbol"),
        "period": _period_key(row.get("as_of") or row.get("event_time") or row.get("period")),
        "prior_as_of": row.get("prior_as_of"),
        "as_of": row.get("as_of") or row.get("event_time"),
        "source": row.get("source") or "FRED",
        "http_source": row.get("http_source"),
        "status": row.get("status") or "ok",
        "reason_code": row.get("reason_code"),
        "formula": row.get("formula"),
        "comparison": row.get("comparison") or ("same_definition_monthly_diff" if metric == "nfp" else "same_series_same_unit"),
        "basis": "monthly_diff" if metric == "nfp" else row.get("basis"),
        "data_class": data_class,
    }


def load_frozen_6a_pack(path: Path | None = None) -> dict[str, Any]:
    target = path or FROZEN_6A_PATH
    if not target.is_file():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("live") is True:
        return {}
    return payload


def load_frozen_6a_documents(path: Path | None = None) -> list[Any]:
    from .policy import sanitize_untrusted
    from .types import EventDocument

    payload = load_frozen_6a_pack(path)
    rows = []
    for item in payload.get("documents") or []:
        rows.append(
            EventDocument(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                publisher=str(item.get("publisher") or ""),
                published_at=item.get("published_at"),
                event_type=str(item.get("event_type") or "other"),
                entities=list(item.get("entities") or []),
                countries=list(item.get("countries") or []),
                claims=list(item.get("claims") or []),
                body=sanitize_untrusted(str(item.get("body") or "")),
                provider=str(item.get("provider") or "official"),
                status=str(item.get("status") or "active"),
            )
        )
    return rows


def load_frozen_6a_facts(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or FROZEN_6A_PATH
    if not target.is_file():
        return []
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("live") is True:
        return []
    rows = []
    for item in payload.get("facts") or []:
        row = dict(item)
        row["data_class"] = payload.get("data_class") or "frozen_provider_audit"
        row["live"] = False
        rows.append(row)
    return rows


def parse_macro_inject(raw: Any) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        parts = raw.replace("|", ",").split(",")
    else:
        parts = []
        for item in raw:
            parts.extend(str(item).replace("|", ",").split(","))
    return frozenset(part.strip().lower() for part in parts if part.strip().lower() in INJECT_KEYS)


def apply_macro_inject(facts: list[dict[str, Any]], tokens: Any) -> list[dict[str, Any]]:
    wanted = parse_macro_inject(tokens)
    if not wanted:
        return list(facts)
    rows = [dict(row) for row in facts]
    if "missing_cpi_baseline" in wanted:
        for row in rows:
            if canonical_metric(str(row.get("metric") or "")) == "cpi":
                row["prior"] = None
                row["consensus"] = None
                row["prior_as_of"] = None
    if "period_mismatch_nfp" in wanted:
        for row in rows:
            if canonical_metric(str(row.get("metric") or "")) == "nfp":
                row["prior"] = 159533.0
                row["prior_basis"] = "employment_stock"
                row["prior_unit"] = "thousands"
    if "source_fail_us2y" in wanted:
        for row in rows:
            if canonical_metric(str(row.get("metric") or "")) == "us2y":
                row["status"] = "error"
                row["reason_code"] = "source_failed"
    if "reverse_cpi" in wanted:
        for row in rows:
            if canonical_metric(str(row.get("metric") or "")) == "cpi":
                actual = _num(row.get("actual"))
                consensus = _num(row.get("consensus"))
                if actual is not None and consensus is not None and actual > consensus:
                    row["actual"] = consensus - abs(actual - consensus)
                elif actual is not None:
                    row["actual"] = actual - 1.0
    return rows


def load_macro_facts(settings: Any = None, *, facts: list[dict[str, Any]] | None = None, inject: Any = None) -> list[dict[str, Any]]:
    if facts is not None:
        rows = [dict(row) for row in facts]
    elif _CACHE["facts"] is not None:
        rows = [dict(row) for row in _CACHE["facts"]]
    else:
        mode = events_data_mode(settings)
        if mode in {"demo", "fixture"}:
            rows = load_frozen_6a_facts()
        elif mode in {"empty", "live"}:
            try:
                from stock_pm.series import collect_live_macro_overlay

                live_rows, _errors, _report = collect_live_macro_overlay(settings)
                rows = [fact_from_fred_row(row, data_class="live_current") for row in live_rows]
            except Exception:
                rows = []
        else:
            rows = []
        _CACHE["facts"] = [dict(row) for row in rows]
    if inject and inject_allowed(settings):
        rows = apply_macro_inject(rows, inject)
    elif inject and not inject_allowed(settings):
        rows = list(rows)
    return rows


def build_market_macro_chains(
    *,
    events: list[TrustedEvent] | None = None,
    facts: list[dict[str, Any]] | None = None,
    settings: Any = None,
    symbols: list[str] | None = None,
    inject: Any = None,
) -> list[dict[str, Any]]:
    numeric = load_macro_facts(settings, facts=facts, inject=inject)
    registry: dict[str, dict[str, Any]] = {}
    for fact in numeric:
        chain = build_numeric_macro_chain(fact, companion_facts=numeric, symbols=symbols)
        registry[chain["chain_id"]] = chain
    for event in events or []:
        analysis = event.analysis or {}
        chain = analysis.get("macro_chain") or build_event_macro_chain(event, analysis)
        if not chain:
            continue
        previous = registry.get(chain["chain_id"])
        if previous and previous.get("metric") in METRIC_FAMILY:
            continue
        registry[chain["chain_id"]] = chain
    return list(registry.values())


def summarize_macro_chains(chains: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in chains if row.get("status") == "ok"]
    degraded = [row for row in chains if row.get("status") == "degraded"]
    unavailable = [row for row in chains if row.get("status") == "unavailable"]
    live_current = [row for row in chains if row.get("data_class") == "live_current"]
    frozen = [row for row in chains if str(row.get("data_class") or "").startswith("frozen")]
    headlines = []
    for row in ok:
        exp = next((layer for layer in row.get("layers") or [] if layer.get("id") == "expectation"), None)
        headlines.append({
            "chain_id": row.get("chain_id"),
            "metric": row.get("metric"),
            "family": row.get("family"),
            "text": (exp or {}).get("text") or "",
            "status": row.get("status"),
            "data_class": row.get("data_class"),
        })
    return {
        "count": len(chains),
        "ok_count": len(ok),
        "degraded_count": len(degraded),
        "unavailable_count": len(unavailable),
        "live_current_count": len(live_current),
        "frozen_count": len(frozen),
        "headlines": headlines,
        "note": FROZEN_NOTE if frozen and not live_current else "Market-level chains cite official facts; stock pages only show mapped exposures.",
    }


def stock_macro_chains(chains: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    selected = []
    for chain in chains:
        if chain.get("metric") == "vix" or chain.get("vix_role") == "risk_confirmation_only" and chain.get("metric") == "vix":
            continue
        hit = None
        for row in chain.get("exposures") or []:
            if str(row.get("symbol") or "").upper() == symbol.upper():
                hit = row
                break
        if hit is None:
            stub_type = str(chain.get("event_type") or "")
            if stub_type:
                stub = TrustedEvent(
                    event_id=str(chain.get("event_id") or chain.get("chain_id")),
                    canonical_title=str(chain.get("metric") or ""),
                    event_type=stub_type,
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
        if not hit:
            continue
        payload = dict(chain)
        payload["why_relevant"] = hit.get("why_relevant")
        payload["channel"] = hit.get("channel")
        payload["mechanism"] = hit.get("mechanism")
        payload["cited_chain_id"] = chain.get("chain_id")
        payload["can_form_direction"] = False
        payload["percent_forecast"] = None
        payload["price_target"] = None
        selected.append(payload)
    return selected


def env_macro_inject() -> str | None:
    return os.getenv("STOCK_PM_MACRO_INJECT")
