"""Phase 8 conditional horizon scenarios. No prices, no vote, no VIX-as-direction.

Inputs: healthy, traceable Phase 6/7 chains only. Search snippets, degraded
rows, and VIX-alone never form direction. can_form_direction is computed;
false means every horizon is withheld and forecast is empty.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .synthesis import (
    _is_directional_ok,
    _is_vix,
    _theme,
    chain_evidence_refs,
    chain_relevant_to_industry,
    chain_relevant_to_stock,
    evaluation_date,
    filter_missing_chains,
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
    "us2y",
})
HORIZON_FILL_HINTS = {
    "short": ("us2y", "wti"),
    "medium": ("cpi", "nfp"),
    "long": ("credit", "war_sanctions"),
}
PRESSURE_TO_SCENARIO = {
    "pressure": "down",
    "relief": "up",
    "present": "range",
}


def _metric(chain: dict[str, Any]) -> str:
    return str(chain.get("metric") or chain.get("event_type") or "")


def _healthy_directional(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for chain in chains or []:
        if not _is_directional_ok(chain):
            continue
        if chain.get("status") != "ok":
            continue
        if _is_vix(chain):
            continue
        if str(chain.get("body_source") or "") == "cse_snippet":
            continue
        if str(chain.get("discovery_role") or "") in {"discovery_candidate", "discovery_only"}:
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


def _scenario_for(chains: list[dict[str, Any]], *, target: str | None) -> str:
    if not chains:
        return "withheld"
    polarities = [polarity(row) for row in chains]
    polarities = [item for item in polarities if item]
    if not polarities:
        return "withheld"
    energy = [row for row in chains if _metric(row) in {"wti", "oil", "energy_supply"}]
    if target == "XOM" and energy:
        energy_pol = {polarity(row) for row in energy if polarity(row)}
        if energy_pol == {"pressure"}:
            return "up"
        if energy_pol == {"relief"}:
            return "down"
    unique = set(polarities)
    if unique == {"pressure"}:
        return "down"
    if unique == {"relief"}:
        return "up"
    if len(unique) > 1:
        return "range"
    return PRESSURE_TO_SCENARIO.get(next(iter(unique)), "range")


def _horizon_text(horizon: str, chains: list[dict[str, Any]], scenario: str, *, target: str | None) -> str:
    label = {"short": "短期", "medium": "中期", "long": "长期"}[horizon]
    if scenario == "withheld" or not chains:
        hints = " / ".join(HORIZON_FILL_HINTS[horizon])
        return f"{label}情景 withheld：缺 {hints} 健康方向链。补齐后将改写该期限情景，不把其他期限结论复制过来。"
    drivers = "、".join(sorted({_metric(row) for row in chains}))
    if horizon == "short":
        lead = next((row for row in chains if _metric(row) in {"us2y", "wti"}), chains[0])
        change = _layer_text(lead, "change") or _layer_text(lead, "fact")
        return f"短期：近端市场序列 {drivers}。{change} → 条件情景 {scenario}，不是把中长期打印复制为日频结论。"
    if horizon == "medium":
        lead = next((row for row in chains if _metric(row) in {"cpi", "nfp"}), chains[0])
        exp = _layer_text(lead, "expectation")
        return f"中期：官方打印 {drivers}。{exp} → 条件情景 {scenario}，不是短端日变动的原文。"
    lead = next((row for row in chains if _metric(row) in {"credit", "war_sanctions", "energy_supply"}), chains[0])
    if target == "NVDA" or _metric(lead) == "us2y":
        return (
            f"长期：久期/贴现路径（{drivers}），把利率事实映射为持续贴现暴露，"
            f"情景 {scenario}。与短期日变动分开陈述，不是同一段结论。"
        )
    if target == "XOM" or _metric(lead) in {"wti", "energy_supply"}:
        return f"长期：能源供应/价格结构（{drivers}）进入生产商收入路径，情景 {scenario}，不是短端油价日变动原文。"
    if target == "JPM" or _metric(lead) in {"credit", "nfp"}:
        return f"长期：信用/融资条件（{drivers}）进入银行资产负债表观察，情景 {scenario}，不是就业打印的原文复制。"
    exp = _layer_text(lead, "expectation")
    return f"长期：结构驱动 {drivers}。{exp} → 条件情景 {scenario}。"


def _what_if_filled(horizon: str, scenario: str) -> str:
    hints = " / ".join(HORIZON_FILL_HINTS[horizon])
    if scenario == "withheld":
        return f"补齐 {hints} 健康链后，将按该期限驱动重算 { {'short': '短期', 'medium': '中期', 'long': '长期'}[horizon] }情景，而不是沿用其他期限结论"
    return f"若 {hints} 反转或被官方撤回，该期限情景失效并改写 What changes"


def _missing_rows(
    chains: list[dict[str, Any]],
    scoped: list[dict[str, Any]],
    *,
    scope: str,
    target: str | None,
    healthy: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    degraded = filter_missing_chains([row for row in chains if row.get("status") != "ok"], scope=scope, target=target)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chain in degraded:
        metric = _metric(chain)
        if not metric or metric in seen:
            continue
        seen.add(metric)
        rows.append({
            "metric": metric,
            "chain": chain.get("chain_id"),
            "reason": chain.get("degrade_reason") or chain.get("status") or "missing",
            "detail": chain.get("degrade_detail") or f"{metric} 链不健康，不进入方向证据",
            "what_changes": f"补齐 {metric} 健康原文后将改写对应期限情景，只降级本链",
        })
    present = {_metric(row) for row in healthy}
    market_ok = {_metric(row) for row in _healthy_directional(chains)}
    if scope == "stock" and target:
        for metric in sorted(market_ok - present):
            if metric in seen:
                continue
            seen.add(metric)
            rows.append({
                "metric": metric,
                "chain": f"exposure:{target}:{metric}",
                "reason": "no_exposure",
                "detail": f"{target} 没有经行业映射的 {metric} 暴露，不能把市场链复制到该股",
                "what_changes": f"仅当 {target} 出现可验证 {metric} 暴露后，该链才进入方向情景",
            })
    if not healthy and not rows:
        for metric in ("us2y", "cpi", "nfp"):
            rows.append({
                "metric": metric,
                "chain": f"missing:{metric}",
                "reason": "missing_directional_chain",
                "detail": f"缺 {metric} 健康方向链",
                "what_changes": f"补齐 {metric} 后将改写对应期限情景，禁止用笼统无法判断代替",
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


def can_form_horizon_direction(chains: list[dict[str, Any]]) -> bool:
    """True only with at least one healthy, non-VIX, non-discovery directional chain."""
    return bool(_healthy_directional(chains))


def _empty_horizon(horizon: str) -> dict[str, Any]:
    return {
        "horizon": horizon,
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
        "text": _horizon_text(horizon, [], "withheld", target=None),
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
    healthy = _healthy_directional(scoped)
    fresh_healthy = [row for row in healthy if is_fresh(row, now=clock)]
    usable = fresh_healthy or healthy
    allowed = can_form_horizon_direction(usable)
    vix = _vix_block(all_chains if scope == "market" else all_chains, usable)
    missing = _missing_rows(all_chains, scoped, scope=scope, target=target, healthy=usable)
    if _is_vix_only(all_chains, usable):
        allowed = False
        usable = []
    horizons = []
    for name in HORIZONS:
        if not allowed:
            horizons.append(_empty_horizon(name))
            continue
        rows = _horizon_chains(usable, name)
        if name == "long" and target == "NVDA":
            rows = rows or [row for row in usable if _metric(row) in {"us2y", "cpi"}]
        scenario = _scenario_for(rows, target=target)
        refs = [ref for row in rows for ref in chain_evidence_refs(row)]
        counters = []
        if (synthesis or {}).get("contradictions"):
            counters.extend(synthesis.get("contradictions") or [])
        if vix.get("present"):
            counters.extend(vix.get("counter_evidence") or [])
        if scenario == "range" and rows:
            counters.append({"text": "该期限驱动方向不一致，两侧证据都保留，不作多数表决"})
        horizons.append({
            "horizon": name,
            "directional_scenario": scenario,
            "direction": None if scenario == "withheld" else scenario,
            "drivers": [{"metric": _metric(row), "theme": _theme(row), "polarity": polarity(row), "chain_id": row.get("chain_id")} for row in rows],
            "driver_metrics": list(dict.fromkeys(_metric(row) for row in rows)),
            "transmission": (
                "先到市场，再按可验证暴露到行业/个股"
                if scope == "market"
                else f"{target} 仅纳入已映射渠道，不复制无关宏观标题"
            ),
            "supporting_evidence": refs,
            "counter_evidence": counters,
            "confidence": "limited" if scenario == "range" else ("medium" if len(rows) >= 2 else "limited" if rows else "insufficient"),
            "invalidation": _what_if_filled(name, scenario),
            "what_changes": _what_if_filled(name, scenario),
            "text": _horizon_text(name, rows, scenario, target=target),
            "percent_forecast": None,
            "price_target": None,
        })
    reason = None
    if not allowed:
        named = "、".join(row["metric"] for row in missing[:4]) or "健康方向链"
        reason = f"can_form_direction=false：缺 {named}。VIX、搜索摘要或降级链不能形成预测。"
    what_changes = {
        "text": (
            reason
            if not allowed
            else "任一期限驱动被官方撤回或反转时，只改写该期限情景，不把其他期限结论机械复制。"
        ),
        "missing": missing,
    }
    return {
        "scope": scope,
        "target": target,
        "as_of": clock.isoformat(),
        "can_form_direction": allowed,
        "reason": reason,
        "horizons": horizons,
        "forecast": None if not allowed else {
            "short": horizons[0]["directional_scenario"],
            "medium": horizons[1]["directional_scenario"],
            "long": horizons[2]["directional_scenario"],
        },
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
