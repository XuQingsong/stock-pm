"""Evidence-bound event analysis. No unsourced numbers or price ranges."""

from __future__ import annotations

from typing import Any

from .exposure import attach_exposures, why_relevant
from .types import TrustedEvent


DISPLAY_SYMBOLS = ("NVDA", "XOM", "JPM", "AAPL")


def _refs(event: TrustedEvent, *, facts_only: bool = False) -> list[dict[str, str]]:
    rows = []
    for source in event.sources:
        if facts_only and source.fact_or_opinion != "fact":
            continue
        if source.content_type == "aggregator":
            continue
        if source.content_type == "research_opinion":
            continue
        rows.append(
            {
                "source_id": source.source_id,
                "source_url": source.source_url,
                "publisher": source.publisher,
                "source_tier": str(source.source_tier),
                "content_type": source.content_type,
                "fact_or_opinion": source.fact_or_opinion,
            }
        )
    return rows


def _opinion_refs(event: TrustedEvent) -> list[dict[str, str]]:
    rows = []
    for source in event.sources:
        if source.content_type != "research_opinion":
            continue
        rows.append(
            {
                "source_id": source.source_id,
                "source_url": source.source_url,
                "publisher": source.publisher,
                "source_tier": str(source.source_tier),
                "content_type": source.content_type,
                "fact_or_opinion": source.fact_or_opinion,
            }
        )
    return rows


def _bound(text: str | None, refs: list[dict[str, str]]) -> dict[str, Any]:
    return {"text": text, "evidence_refs": list(refs)}


def _conflicts(event: TrustedEvent) -> list[dict[str, str]]:
    support = [row for row in event.claims if row.polarity == "supports"]
    contra = [row for row in event.claims if row.polarity == "contradicts"]
    rows = []
    if support and contra:
        rows.append(
            {
                "code": "claim_conflict",
                "text": "同一事件存在互相矛盾的 claim，降低置信度，不把任一侧写成已定价方向",
            }
        )
    return rows


def confidence_rule(event: TrustedEvent) -> dict[str, Any]:
    official = [row for row in event.sources if row.source_tier == 1]
    media = [row for row in event.sources if row.source_tier == 2]
    conflicts = _conflicts(event)
    if event.status == "revoked":
        result = "revoked"
    elif conflicts:
        result = "low"
    elif official and media:
        result = "high"
    elif official:
        result = "medium"
    elif media:
        result = "limited"
    else:
        result = "insufficient"
    return {
        "revoked": event.status == "revoked",
        "conflict_count": len(conflicts),
        "tier1_count": len(official),
        "tier2_count": len(media),
        "result": result,
    }


def _confidence(event: TrustedEvent) -> str:
    return str(confidence_rule(event)["result"])


def _withhold(reason: str) -> dict[str, Any]:
    return {
        "status": "withheld",
        "reason": reason,
        "direction": None,
        "horizon": None,
        "percent_forecast": None,
        "price_target": None,
    }


def analyze_event(event: TrustedEvent, *, symbols: list[str] | None = None) -> dict[str, Any]:
    wanted = [item.upper() for item in (symbols or DISPLAY_SYMBOLS)]
    official_refs = [row for row in _refs(event, facts_only=True) if row["content_type"] == "official_fact"]
    fact_refs = _refs(event, facts_only=True)
    all_refs = _refs(event)
    opinion_refs = _opinion_refs(event)
    conflicts = _conflicts(event)
    confidence = _confidence(event)
    bound_refs = official_refs or fact_refs or all_refs
    if event.status == "revoked":
        change = "官方/后续报道撤销或否定先前表述"
        what = "撤销后主结论回到事件发生前的观察状态"
    elif event.status == "updated":
        change = "同一事件出现更新报道，刷新时间线，不重复制造一条新影响结论"
        what = "更新时间线与失效条件，不重复叠加一条新方向"
    else:
        change = "相对此前无该事件的基线，市场首次纳入该已确认事实"
        what = "把该事件纳入相关标的的观察清单，不改写无暴露股票的主结论"

    if not bound_refs:
        analysis = {
            "confirmed_facts": [],
            "change_vs_baseline": _bound(None, []),
            "mechanism": _bound(None, []),
            "affected_markets": [],
            "exposures": [],
            "direction": _bound(None, []),
            "horizon": _bound(None, []),
            "confidence": _bound("insufficient", []),
            "counter_evidence": [_bound("没有可点击原文，结论 withhold", [])],
            "invalidation": _bound(event.invalidation, []),
            "what_changes": _bound("主结论不改写", []),
            "withheld": _withhold("证据不足，禁止生成无来源数字或价格预测"),
            "evidence_refs": [],
            "opinion_refs": opinion_refs,
            "conflict_count": 0,
            "confidence_rule": confidence_rule(event),
            "percent_forecast": None,
            "price_target": None,
            "answers": {
                "what_happened": "证据不足，withhold",
                "credibility": "insufficient",
                "why_relevant": "市场中心展示全部事件；个股页需行业映射",
                "how_long": event.duration,
                "invalidates_when": event.invalidation,
            },
        }
        event.analysis = analysis
        return analysis

    mechanism = {
        "war_sanctions": "供应中断/制裁 → 油价或风险溢价 → 行业暴露 → 个股",
        "energy_supply": "能源供应变化 → 油价 → 生产商收入或下游成本",
        "central_bank_rates": "利率事实 → 贴现率预期 → 久期暴露",
        "inflation_employment": "通胀/就业事实 → 利率预期 → 久期或周期暴露",
        "vix_risk": "VIX 只确认风险状态，经风险溢价放大，不直接推个股涨跌",
        "gold_wti": "商品价格事实 → 对应商品链，不跨链复制",
        "company_filing": "公司原文公告只传导到该主体，不复制到无关股票",
    }.get(event.event_type, "仅在有行业映射和公司暴露时传导")

    exposures = attach_exposures(event, wanted)
    direction = None
    horizon = event.duration
    if confidence in {"insufficient", "revoked"} or not official_refs:
        withheld = _withhold("缺少 Tier 1 官方事实或事件已撤销，不输出方向")
    elif conflicts:
        withheld = _withhold("矛盾 claim 存在，方向 withhold")
    else:
        withheld = {
            "status": "observable",
            "reason": "可观察传导方向/期限，不是个股交易指令或价格区间",
            "direction": "pressure" if event.severity in {"high", "critical"} else "watch",
            "horizon": horizon,
            "percent_forecast": None,
            "price_target": None,
        }
        direction = withheld["direction"]

    analysis = {
        "confirmed_facts": [
            {
                "text": event.canonical_title,
                "evidence_refs": official_refs or bound_refs[:1],
            }
        ],
        "change_vs_baseline": _bound(change, bound_refs),
        "mechanism": _bound(mechanism, bound_refs),
        "affected_markets": sorted({row["channel"] for row in exposures}) or ["market_background"],
        "exposures": exposures,
        "direction": _bound(direction, bound_refs if direction else []),
        "horizon": _bound(horizon, bound_refs),
        "confidence": _bound(confidence, bound_refs),
        "counter_evidence": [_bound(row["text"], bound_refs) for row in conflicts]
        + [_bound(event.invalidation or "", bound_refs)],
        "invalidation": _bound(event.invalidation, bound_refs),
        "what_changes": _bound(what, bound_refs),
        "withheld": withheld,
        "evidence_refs": bound_refs,
        "opinion_refs": opinion_refs,
        "conflict_count": len(conflicts),
        "confidence_rule": confidence_rule(event),
        "percent_forecast": None,
        "price_target": None,
        "vix_role": "risk_confirmation_only" if event.event_type == "vix_risk" else "not_applicable",
        "answers": {
            "what_happened": event.canonical_title,
            "credibility": confidence,
            "why_relevant": "市场事件中心完整展示；个股页只保留有暴露映射的事件",
            "how_long": horizon,
            "invalidates_when": event.invalidation,
        },
    }
    event.analysis = analysis
    return analysis


def symbol_event_view(event: TrustedEvent, symbol: str) -> dict[str, Any] | None:
    hit = why_relevant(event, symbol)
    if not hit:
        return None
    payload = event.as_dict()
    payload["why_relevant"] = hit["why_relevant"]
    payload["channel"] = hit["channel"]
    payload["mechanism"] = hit["mechanism"]
    analysis = dict(event.analysis or {})
    answers = dict(analysis.get("answers") or {})
    answers["why_relevant"] = hit["why_relevant"]
    analysis["answers"] = answers
    payload["analysis"] = analysis
    return payload
