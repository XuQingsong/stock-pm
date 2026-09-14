"""Phase 8 conditional horizon scenarios. No prices, no vote, no VIX-as-direction.

Inputs: healthy, current Tier-1 originals only. Search snippets, Tier 2/3,
degraded/stale/revoked rows, and VIX-alone never form direction. Each horizon
has its own can_form_direction; withheld horizons are omitted from forecast.
Direction follows explicit target/channel exposure, not a generic polarity map.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .policy import DISCOVERY_BODY_SOURCES, DISCOVERY_ROLES, tier1_ref_gaps
from .synthesis import (
    _is_directional_ok,
    _is_vix,
    _theme,
    chain_evidence_refs,
    chain_relevant_to_industry,
    chain_relevant_to_stock,
    evaluation_date,
    filter_missing_chains,
    freshness_state,
    is_fresh,
    polarity,
    stock_macro_chains,
)

DIRECTIONAL_SCENARIOS = ("up", "down", "range", "withheld")
HORIZONS = ("short", "medium", "long")
SHORT_METRICS = frozenset({"us2y", "wti", "oil", "broad_usd_proxy", "policy_rate"})
MEDIUM_METRICS = frozenset({"cpi", "core_cpi", "nfp", "inflation_employment"})
LONG_METRICS = frozenset({
    "credit",
    "war_sanctions",
    "energy_supply",
    "sovereign_or_corporate_debt",
})
HORIZON_FILL_HINTS = {
    "short": ("us2y", "wti"),
    "medium": ("cpi", "nfp"),
    "long": ("credit", "war_sanctions", "energy_supply"),
}
OPPOSING_CHANNELS = frozenset({"nim_vs_credit", "mixed_energy"})
CHANNEL_DIRECTION = {
    "duration": {"pressure": "down", "relief": "up"},
    "discount": {"pressure": "down", "relief": "up"},
    "commodity_revenue": {"pressure": "up", "relief": "down"},
    "credit_conditions": {"pressure": "down", "relief": "up"},
    "risk_premium": {"pressure": "down", "relief": "up"},
    "fx": {"pressure": "down", "relief": "up"},
}
BLOCKED_BODY = DISCOVERY_BODY_SOURCES
BLOCKED_ROLES = DISCOVERY_ROLES
BLOCKED_CONTENT = frozenset({"media_report", "research_opinion", "aggregator"})
BLOCKED_FRESHNESS = frozenset({"stale", "future"})
BLOCKED_STATUS = frozenset({"stale", "degraded", "revoked", "superseded", "unavailable"})


def _metric(chain: dict[str, Any]) -> str:
    return str(chain.get("metric") or chain.get("event_type") or "")


def _raw_layer_refs(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Layer evidence refs as stored. Do not invent Tier-1 metadata."""
    out: list[dict[str, Any]] = []
    for layer in chain.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        for ref in layer.get("evidence_refs") or []:
            if isinstance(ref, dict):
                out.append(ref)
    return out


def _ref_is_current_tier1(ref: dict[str, Any]) -> bool:
    return not tier1_ref_gaps(ref)


def _tier1_gaps_for_chain(chain: dict[str, Any]) -> list[str]:
    refs = _raw_layer_refs(chain)
    if not refs:
        return ["refs"]
    best: list[str] | None = None
    for ref in refs:
        gaps = tier1_ref_gaps(ref)
        if not gaps:
            return []
        if best is None or len(gaps) < len(best):
            best = gaps
    return best or ["refs"]


def _tier1_gap_reason(chains: list[dict[str, Any]]) -> str | None:
    best: list[str] | None = None
    for chain in chains or []:
        gaps = _tier1_gaps_for_chain(chain)
        if not gaps:
            return None
        if best is None or len(gaps) < len(best):
            best = gaps
    if not best:
        return None
    return "Tier1 门禁失败：缺 " + "、".join(best)


def _has_current_tier1(chain: dict[str, Any]) -> bool:
    if str(chain.get("body_source") or "") in BLOCKED_BODY:
        return False
    if str(chain.get("discovery_role") or "") in BLOCKED_ROLES:
        return False
    if str(chain.get("fact_or_opinion") or "") in {"opinion", "reported"}:
        return False
    if str(chain.get("content_type") or "") in BLOCKED_CONTENT:
        return False
    return not _tier1_gaps_for_chain(chain)


def _healthy_directional(chains: list[dict[str, Any]], *, now: date | None = None) -> list[dict[str, Any]]:
    clock = evaluation_date(now)
    rows = []
    for chain in chains or []:
        if not _is_directional_ok(chain):
            continue
        if chain.get("status") != "ok":
            continue
        if str(chain.get("status") or "") in BLOCKED_STATUS:
            continue
        if _is_vix(chain):
            continue
        if str(chain.get("body_source") or "") in BLOCKED_BODY:
            continue
        if str(chain.get("discovery_role") or "") in BLOCKED_ROLES:
            continue
        state = freshness_state(chain, now=clock)
        if state.get("reason") in BLOCKED_FRESHNESS or not is_fresh(chain, now=clock):
            continue
        if not _has_current_tier1(chain):
            continue
        if not chain_evidence_refs(chain):
            continue
        rows.append(chain)
    return rows


def _scope_chains(chains: list[dict[str, Any]], *, scope: str, target: str | None) -> list[dict[str, Any]]:
    if scope == "stock" and target:
        mapped = [row for row in stock_macro_chains(chains, target) if row.get("status") == "ok"]
        if mapped:
            return mapped
        return [row for row in chains if chain_relevant_to_stock(row, target) and row.get("status") == "ok"]
    if scope == "industry" and target:
        return [row for row in chains if chain_relevant_to_industry(row, target)]
    return list(chains or [])


def _horizon_metrics(horizon: str) -> frozenset[str]:
    if horizon == "short":
        return SHORT_METRICS
    if horizon == "medium":
        return MEDIUM_METRICS
    return LONG_METRICS


def _horizon_chains(chains: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    wanted = _horizon_metrics(horizon)
    return [row for row in chains if _metric(row) in wanted]


def _layer_text(chain: dict[str, Any], name: str) -> str:
    for row in chain.get("layers") or []:
        if row.get("id") == name:
            return str(row.get("text") or "")
    return ""


def _mapped_channel(chain: dict[str, Any], *, target: str | None) -> str | None:
    if target:
        mapped = stock_macro_chains([chain], target)
        if mapped:
            channel = str(mapped[0].get("channel") or "") or None
            if channel:
                return channel
        if not chain_relevant_to_stock(chain, target):
            return None
    theme = _theme(chain)
    metric = _metric(chain)
    if target == "NVDA" and (theme == "rates" or metric in SHORT_METRICS | MEDIUM_METRICS):
        return "duration"
    if target == "XOM" and (theme == "energy" or metric in {"wti", "oil", "energy_supply"}):
        return "commodity_revenue"
    if target == "JPM":
        if theme == "rates" or metric in {"us2y", "cpi", "core_cpi", "nfp", "inflation_employment", "policy_rate"}:
            return "nim_vs_credit"
        if theme == "credit" or metric == "credit":
            return "credit_conditions"
        if theme == "geopolitics":
            return "risk_premium"
    if target in {"AAPL", "NOK"}:
        return None
    if not target:
        if theme == "rates":
            return "discount"
        if theme == "energy":
            return "mixed_energy"
        if theme == "credit":
            return "credit_conditions"
        if theme == "geopolitics":
            return "risk_premium"
        if theme == "fx":
            return "fx"
    return None


def _effective_channel(chain: dict[str, Any], *, target: str | None) -> str | None:
    channel = _mapped_channel(chain, target=target)
    theme = _theme(chain)
    metric = _metric(chain)
    if target == "JPM" and (theme == "rates" or metric in {"us2y", "cpi", "core_cpi", "nfp", "inflation_employment", "policy_rate"}):
        return "nim_vs_credit"
    if target == "NVDA" and theme == "rates":
        return "duration"
    if target == "XOM" and theme == "energy":
        return "commodity_revenue"
    if channel == "duration" or (target == "NVDA" and channel in {"duration", "risk_premium"} and theme == "rates"):
        return channel or "duration"
    return channel


def _scenario_from_channel(channel: str | None, pol: str | None) -> str:
    if not channel:
        return "withheld"
    if channel in OPPOSING_CHANNELS:
        return "range"
    mapping = CHANNEL_DIRECTION.get(channel)
    if not mapping:
        return "withheld"
    if pol == "present":
        return "range"
    if not pol:
        return "withheld"
    return mapping.get(pol, "range")


def _conflict_hits_horizon(
    synthesis: dict[str, Any] | None,
    *,
    metrics: set[str],
    themes: set[str],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in (synthesis or {}).get("contradictions") or []:
        if not isinstance(item, dict):
            continue
        side_metrics: set[str] = set()
        for side in item.get("sides") or []:
            if isinstance(side, dict):
                side_metrics.update(str(value) for value in (side.get("metrics") or []))
        theme = str(item.get("theme") or "")
        if (side_metrics and side_metrics & metrics) or (theme and theme in themes) or (metrics & set(item.get("metrics") or [])):
            hits.append(item)
    return hits


def _combine_scenarios(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "withheld"
    scenarios = {item[1] for item in rows}
    channels = {item[0] for item in rows}
    if "withheld" in scenarios and len(scenarios) == 1:
        return "withheld"
    scenarios.discard("withheld")
    if not scenarios:
        return "withheld"
    if channels & OPPOSING_CHANNELS:
        return "range"
    if scenarios == {"up"}:
        return "up"
    if scenarios == {"down"}:
        return "down"
    return "range"


def _scenario_for(chains: list[dict[str, Any]], *, target: str | None, synthesis: dict[str, Any] | None = None) -> str:
    if not chains:
        return "withheld"
    mapped: list[tuple[str, str]] = []
    for row in chains:
        channel = _effective_channel(row, target=target)
        if not channel:
            continue
        mapped.append((channel, _scenario_from_channel(channel, polarity(row))))
    scenario = _combine_scenarios(mapped)
    if scenario == "withheld":
        return "withheld"
    metrics = {_metric(row) for row in chains}
    themes = {_theme(row) for row in chains}
    if _conflict_hits_horizon(synthesis, metrics=metrics, themes=themes):
        return "range" if scenario != "withheld" else "withheld"
    return scenario


def _horizon_text(horizon: str, chains: list[dict[str, Any]], scenario: str, *, target: str | None, reason: str | None = None) -> str:
    label = {"short": "短期", "medium": "中期", "long": "长期"}[horizon]
    if scenario == "withheld" or not chains:
        hints = " / ".join(HORIZON_FILL_HINTS[horizon])
        extra = f" {reason}" if reason else ""
        return f"{label}情景 withheld：缺 {hints} 且与该期限匹配的健康方向链。{extra}补齐后将改写该期限情景，不把其他期限结论复制过来。"
    drivers = "、".join(sorted({_metric(row) for row in chains}))
    channels = "、".join(sorted({ch for ch in (_effective_channel(row, target=target) or "" for row in chains) if ch}))
    if horizon == "short":
        lead = next((row for row in chains if _metric(row) in {"us2y", "wti"}), chains[0])
        change = _layer_text(lead, "change") or _layer_text(lead, "fact")
        if target == "NVDA" or "duration" in channels:
            return f"短期：久期/贴现暴露（{drivers}），利率路径 → 条件情景 {scenario}。{change} 不是把中长期打印复制为日频结论。"
        if target == "XOM" or "commodity_revenue" in channels:
            return f"短期：能源/油价收入路径（{drivers}）→ 条件情景 {scenario}。{change}"
        if target == "JPM" or "nim_vs_credit" in channels:
            return f"短期：银行 NIM 与信用相反渠道（{drivers}）→ 条件情景 {scenario}，不作任意涨跌。"
        return f"短期：近端市场序列 {drivers}，渠道 {channels or '未映射'}。{change} → 条件情景 {scenario}，不是把中长期打印复制为日频结论。"
    if horizon == "medium":
        lead = next((row for row in chains if _metric(row) in {"cpi", "nfp"}), chains[0])
        exp = _layer_text(lead, "expectation")
        if target == "JPM" or "nim_vs_credit" in channels:
            return f"中期：银行就业/通胀打印（{drivers}，含 nfp）走 NIM vs 信用，情景 {scenario}，不是消费者电子路径。"
        return f"中期：官方打印 {drivers}，渠道 {channels or '未映射'}。{exp} → 条件情景 {scenario}，不是短端日变动的原文。"
    lead = next((row for row in chains if _metric(row) in LONG_METRICS), chains[0])
    if target == "NVDA" or "duration" in channels:
        return (
            f"长期：结构/制裁/信用持续证据（{drivers}），渠道 {channels}，"
            f"情景 {scenario}。日频 US2Y 或月频 CPI 不能改写为本期限方向。"
        )
    if target == "XOM" or "commodity_revenue" in channels:
        return f"长期：能源供应结构（{drivers}）进入生产商收入路径，情景 {scenario}，不是短端油价日变动原文。"
    if target == "JPM" or "nim_vs_credit" in channels or "credit_conditions" in channels:
        return (
            f"长期：银行 NIM 与信用渠道（{drivers} / {channels}）存在相反暴露时只给 range/withheld，"
            f"情景 {scenario}，不是就业打印的原文复制。"
        )
    exp = _layer_text(lead, "expectation")
    return f"长期：结构驱动 {drivers}。{exp} → 条件情景 {scenario}。"


def _what_if_filled(horizon: str, scenario: str) -> str:
    hints = " / ".join(HORIZON_FILL_HINTS[horizon])
    if scenario == "withheld":
        return f"补齐 {hints} 且与该期限匹配的健康链后，将按该期限驱动重算 { {'short': '短期', 'medium': '中期', 'long': '长期'}[horizon] }情景，而不是沿用其他期限结论"
    return f"若 {hints} 反转、被官方撤回或出现相关综合冲突，该期限情景失效并改写 What changes"


def _horizon_missing(
    horizon: str,
    *,
    scoped_healthy: list[dict[str, Any]],
    all_chains: list[dict[str, Any]],
    scope: str,
    target: str | None,
    reason: str | None = None,
) -> list[dict[str, Any]]:
    wanted = _horizon_metrics(horizon)
    present = {_metric(row) for row in scoped_healthy if _metric(row) in wanted}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    degraded = filter_missing_chains(
        [row for row in all_chains if row.get("status") != "ok" and _metric(row) in wanted],
        scope=scope,
        target=target,
    )
    for chain in degraded:
        metric = _metric(chain)
        if not metric or metric in seen:
            continue
        seen.add(metric)
        rows.append({
            "metric": metric,
            "chain": chain.get("chain_id"),
            "horizon": horizon,
            "reason": chain.get("degrade_reason") or chain.get("status") or "missing",
            "detail": chain.get("degrade_detail") or f"{metric} 链不健康，不进入 {horizon} 方向证据",
            "what_changes": f"补齐 {metric} 健康原文后将改写 {horizon} 情景，只降级本链",
        })
    if not present:
        for metric in HORIZON_FILL_HINTS[horizon]:
            if metric in seen:
                continue
            seen.add(metric)
            detail = f"缺 {metric} 且与 {horizon} 匹配的健康方向链"
            if horizon == "long":
                detail = f"缺长期持续证据 {metric}；日频 US2Y / 月频 CPI 不能改写成长期预测"
            rows.append({
                "metric": metric,
                "chain": f"missing:{horizon}:{metric}",
                "horizon": horizon,
                "reason": reason or "missing_horizon_evidence",
                "detail": detail,
                "what_changes": f"补齐 {metric} 后将改写 {horizon} 情景，禁止用空泛缺口说明代替",
            })
    return rows


def _missing_rows(
    chains: list[dict[str, Any]],
    scoped: list[dict[str, Any]],
    *,
    scope: str,
    target: str | None,
    healthy: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for horizon in HORIZONS:
        for row in _horizon_missing(
            horizon,
            scoped_healthy=_horizon_chains(healthy, horizon),
            all_chains=chains,
            scope=scope,
            target=target,
        ):
            key = f"{row.get('horizon')}:{row.get('metric')}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    present = {_metric(row) for row in healthy}
    market_ok = {_metric(row) for row in _healthy_directional(chains)}
    for chain in scoped:
        if chain.get("status") != "ok" or _is_vix(chain):
            continue
        if _has_current_tier1(chain):
            continue
        metric = _metric(chain)
        key = f"tier1:{metric}"
        if not metric or key in seen:
            continue
        seen.add(key)
        gaps = _tier1_gaps_for_chain(chain)
        named = "、".join(gaps) or "refs"
        rows.append({
            "metric": metric,
            "chain": chain.get("chain_id"),
            "reason": "tier1_gate_failed",
            "detail": f"Tier1 门禁失败：缺 {named}",
            "what_changes": f"补齐显式 {named} 后才允许该链进入方向证据，禁止用 URL 或默认元数据晋级",
        })
    if scope == "stock" and target:
        for metric in sorted(market_ok - present):
            key = f"exposure:{metric}"
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "metric": metric,
                "chain": f"exposure:{target}:{metric}",
                "reason": "no_exposure",
                "detail": f"{target} 没有经行业映射的 {metric} 暴露，不能把市场链复制到该股",
                "what_changes": f"仅当 {target} 出现可验证 {metric} 暴露后，该链才进入方向情景",
            })
    del scoped
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
            "counter_evidence": ["VIX 单独存在时不得写成涨跌预测"],
            "chain_id": None,
            "evidence_refs": [],
        }
    amplifies = bool(directional) and any(
        str((layer.get("direction") if isinstance(layer, dict) else "") or "") == "up"
        for layer in vix.get("layers") or []
        if isinstance(layer, dict) and layer.get("id") == "change"
    )
    return {
        "role": "risk_confirmation_only",
        "present": True,
        "amplifies": amplifies,
        "sets_direction": False,
        "copied_to_all_stocks": False,
        "text": (
            "VIX 上升确认/放大已有风险状态，不单独形成方向，并保留反证"
            if amplifies
            else "VIX 只确认风险状态，不能单独推导方向；反证为 VIX 回落或没有其他健康方向链"
        ),
        "counter_evidence": [
            "VIX 回落或仅有 VIX 时不得形成方向",
            "VIX 不是方向证据，只确认/放大已有风险",
        ],
        "chain_id": vix.get("chain_id"),
        "evidence_refs": chain_evidence_refs(vix),
    }


def can_form_horizon_direction(chains: list[dict[str, Any]], *, now: date | None = None) -> bool:
    """True only with at least one healthy, current Tier-1, non-VIX, non-discovery directional chain."""
    return bool(_healthy_directional(chains, now=now))


def _empty_horizon(horizon: str, *, missing: list[dict[str, Any]] | None = None, reason: str | None = None) -> dict[str, Any]:
    rows = missing or []
    return {
        "horizon": horizon,
        "can_form_direction": False,
        "reason": reason or f"can_form_direction=false：{horizon} 缺匹配期限的健康 Tier1 方向链",
        "directional_scenario": "withheld",
        "direction": None,
        "drivers": [],
        "driver_metrics": [],
        "transmission": "",
        "supporting_evidence": [],
        "counter_evidence": [],
        "confidence": "insufficient",
        "invalidation": _what_if_filled(horizon, "withheld"),
        "what_changes": _what_if_filled(horizon, "withheld"),
        "missing": rows,
        "text": _horizon_text(horizon, [], "withheld", target=None, reason=reason),
        "percent_forecast": None,
        "price_target": None,
    }


def build_horizon_forecast(
    chains: list[dict[str, Any]] | None,
    *,
    synthesis: dict[str, Any] | None = None,
    scope: str = "market",
    target: str | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    clock = evaluation_date(now)
    all_chains = list(chains or [])
    scoped = _scope_chains(all_chains, scope=scope, target=target)
    healthy = _healthy_directional(scoped, now=clock)
    if _is_vix_only(all_chains, healthy):
        healthy = []
    vix = _vix_block(all_chains, healthy)
    missing = _missing_rows(all_chains, scoped, scope=scope, target=target, healthy=healthy)
    horizons = []
    for name in HORIZONS:
        rows = _horizon_chains(healthy, name)
        horizon_missing = [row for row in missing if row.get("horizon") == name] or _horizon_missing(
            name, scoped_healthy=rows, all_chains=all_chains, scope=scope, target=target
        )
        if not rows:
            reason = None
            if name == "long" and any(_metric(row) in {"us2y", "cpi", "nfp", "core_cpi"} for row in healthy):
                reason = "日频/月频打印不能改写成长期预测"
            horizons.append(_empty_horizon(name, missing=horizon_missing, reason=reason))
            continue
        scenario = _scenario_for(rows, target=target, synthesis=synthesis)
        conflicts = _conflict_hits_horizon(
            synthesis,
            metrics={_metric(row) for row in rows},
            themes={_theme(row) for row in rows},
        )
        if conflicts and scenario in {"up", "down"}:
            scenario = "range"
        channel_set = {_effective_channel(row, target=target) for row in rows}
        if None in channel_set and len(channel_set) == 1:
            horizons.append(_empty_horizon(name, missing=horizon_missing, reason="没有与该标的匹配的传导渠道"))
            continue
        if scenario == "withheld":
            horizons.append(_empty_horizon(name, missing=horizon_missing, reason="暴露规则不能形成明确方向"))
            continue
        refs = [ref for row in rows for ref in _raw_layer_refs(row) if _ref_is_current_tier1(ref)]
        if not refs:
            reason = _tier1_gap_reason(rows) or "方向证据缺少当前 Tier1 原文"
            horizons.append(_empty_horizon(name, missing=horizon_missing, reason=reason))
            continue
        counters: list[Any] = []
        if conflicts:
            counters.extend(conflicts)
            counters.append("相关综合冲突阻止该期限输出 up/down")
        if vix.get("present"):
            counters.extend(vix.get("counter_evidence") or [])
        if scenario == "range" and rows:
            counters.append({"text": "该期限驱动方向不一致或存在相反渠道，两侧证据都保留，不作多数表决"})
        formed = True
        horizons.append({
            "horizon": name,
            "can_form_direction": formed,
            "reason": None,
            "directional_scenario": scenario,
            "direction": None if scenario == "withheld" else scenario,
            "drivers": [
                {
                    "metric": _metric(row),
                    "theme": _theme(row),
                    "channel": _effective_channel(row, target=target),
                    "polarity": polarity(row),
                    "chain_id": row.get("chain_id"),
                }
                for row in rows
            ],
            "driver_metrics": list(dict.fromkeys(_metric(row) for row in rows)),
            "transmission": (
                "先到市场，再按可验证暴露到行业/个股"
                if scope == "market"
                else f"{target} 仅纳入已映射渠道，不复制无关宏观标题；银行等相反渠道为 range/withheld"
            ),
            "supporting_evidence": refs,
            "counter_evidence": counters,
            "confidence": (
                "limited"
                if scenario == "range" or conflicts
                else ("medium" if len(rows) >= 2 else "limited")
            ),
            "invalidation": _what_if_filled(name, scenario),
            "what_changes": _what_if_filled(name, scenario),
            "missing": horizon_missing,
            "text": _horizon_text(name, rows, scenario, target=target),
            "percent_forecast": None,
            "price_target": None,
        })
    formed = [row for row in horizons if row.get("can_form_direction") is True]
    withheld = [row["horizon"] for row in horizons if row.get("can_form_direction") is not True]
    allowed = bool(formed)
    reason = None
    if not allowed:
        named = "、".join(row["metric"] for row in missing[:4]) or "健康方向链"
        reason = f"can_form_direction=false：缺 {named}。VIX、搜索摘要、Tier2/3 或降级链不能形成预测。"
    what_changes = {
        "text": (
            reason
            if not allowed
            else (
                "任一期限驱动被官方撤回、反转或出现相关综合冲突时，只改写该期限情景；"
                + (f"未形成方向的期限：{', '.join(withheld)}。" if withheld else "")
            )
        ),
        "missing": missing,
        "withheld_horizons": withheld,
        "formed_horizons": [row["horizon"] for row in formed],
    }
    forecast = {row["horizon"]: row["directional_scenario"] for row in formed} if formed else None
    return {
        "scope": scope,
        "target": target,
        "as_of": clock.isoformat(),
        "can_form_direction": allowed,
        "reason": reason,
        "formed_horizons": [row["horizon"] for row in formed],
        "withheld_horizons": withheld,
        "horizons": horizons,
        "forecast": forecast,
        "missing": missing,
        "what_changes": what_changes,
        "vix": vix,
        "percent_forecast": None,
        "price_target": None,
        "win_rate": None,
        "kind": "conditional_horizon_scenario",
        "majority_vote": False,
    }


def _is_vix_only(all_chains: list[dict[str, Any]], usable: list[dict[str, Any]]) -> bool:
    if usable:
        return False
    return any(_is_vix(row) and row.get("status") == "ok" for row in all_chains)
