"""Evidence-bound event analysis. No unsourced numbers or price ranges."""

from __future__ import annotations

from typing import Any

from .evidence import current_claims, evolution_path, excerpt_supports_claim, infer_phase, publisher_key, source_metrics
from .exposure import attach_exposures, why_relevant
from .types import EventClaim, TrustedEvent


DISPLAY_SYMBOLS = ("NVDA", "XOM", "JPM", "AAPL")


def _refs(event: TrustedEvent, *, facts_only: bool = False, current_only: bool = False) -> list[dict[str, str]]:
    rows = []
    current_urls = {row.source_url for row in current_claims(event)} if current_only else None
    for source in event.sources:
        if getattr(source, "evidence_role", "event_fact") == "regime_catalog":
            continue
        if facts_only and source.fact_or_opinion != "fact":
            continue
        if source.content_type == "aggregator":
            continue
        if source.content_type == "research_opinion":
            continue
        if current_urls is not None and source.source_url not in current_urls:
            continue
        rows.append(
            {
                "source_id": source.source_id,
                "source_url": source.source_url,
                "publisher": source.publisher,
                "source_tier": str(source.source_tier),
                "content_type": source.content_type,
                "fact_or_opinion": source.fact_or_opinion,
                "document_role": getattr(source, "document_role", None),
                "published_at": source.published_at,
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


def _as_of_window(left: EventClaim, right: EventClaim, *, days: int = 14) -> bool:
    from datetime import datetime

    raw = [left.observed_at or left.valid_from, right.observed_at or right.valid_from]
    stamps = []
    for item in raw:
        if not item:
            return False
        try:
            stamps.append(datetime.fromisoformat(str(item).replace("Z", "+00:00")))
        except ValueError:
            return False
    return abs((stamps[0] - stamps[1]).days) <= days


def _conflicts(event: TrustedEvent) -> list[dict[str, str]]:
    """Only contemporaneous, different-publisher contradictions count.

    Same-publisher sequential forecasts are supersession, not conflict.
    """
    live = current_claims(event)
    support = [row for row in live if row.polarity == "supports"]
    contra = [row for row in live if row.polarity == "contradicts"]
    rows = []
    for left in support:
        for right in contra:
            if publisher_key(left.publisher, left.source_url) == publisher_key(right.publisher, right.source_url):
                continue
            if not _as_of_window(left, right):
                continue
            rows.append(
                {
                    "code": "claim_conflict",
                    "text": "同一 as-of 窗口内不同发布方对同一可比较 claim 冲突，降低当前置信度，不把任一侧写成已定价方向",
                }
            )
            return rows
    return rows


def confidence_rule(event: TrustedEvent) -> dict[str, Any]:
    official = [
        row
        for row in event.sources
        if row.source_tier == 1 and getattr(row, "evidence_role", "event_fact") != "regime_catalog"
    ]
    media = [row for row in event.sources if row.source_tier == 2]
    metrics = source_metrics(event.sources, event.claims)
    independent = int(metrics.get("independent_publisher_count") or 0)
    conflicts = _conflicts(event)
    if event.status == "revoked":
        result = "revoked"
    elif conflicts:
        result = "low"
    elif official and media and independent >= 2:
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
        "independent_publisher_count": independent,
        "document_count": metrics.get("document_count"),
        "publisher_count": metrics.get("publisher_count"),
        "superseded_count": metrics.get("superseded_count"),
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


LAYER_ORDER = ("fact", "change", "expectation", "impact", "what_changes")
_EMPTY_LAYER_TEXT = {"", "—", "-", "withhold", "none", "null"}


def _layer(
    event_id: str,
    name: str,
    text: str | None,
    cites: list[str],
    refs: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": name,
        "layer_id": f"{name}:{event_id}",
        "text": text or "",
        "cites": list(cites),
        "evidence_refs": list(refs or []),
        **extra,
    }


def causal_chain_is_complete(chain: dict[str, Any] | None) -> bool:
    """True only when all five layers are non-empty and cite the previous layer."""
    layers = {str(row.get("id")): row for row in (chain or {}).get("layers") or [] if isinstance(row, dict)}
    prev_id = None
    for name in LAYER_ORDER:
        row = layers.get(name)
        if not row:
            return False
        text = str(row.get("text") or "").strip()
        if text.lower() in _EMPTY_LAYER_TEXT:
            return False
        layer_id = str(row.get("layer_id") or "")
        if not layer_id:
            return False
        cites = {str(item) for item in (row.get("cites") or []) if item}
        if prev_id and prev_id not in cites:
            return False
        prev_id = layer_id
    fact = layers["fact"]
    excerpt = str(fact.get("excerpt") or "").strip()
    refs = [row for row in (fact.get("evidence_refs") or []) if isinstance(row, dict)]
    if not excerpt or not any(str(row.get("source_url") or "").startswith("http") for row in refs):
        return False
    exp = layers["expectation"]
    if not str(exp.get("direction") or "").strip():
        return False
    if not str(exp.get("horizon") or "").strip():
        return False
    if not str(exp.get("confidence") or "").strip():
        return False
    exposures = [row for row in (layers["impact"].get("exposures") or []) if isinstance(row, dict)]
    if not exposures:
        return False
    if not all(
        str(row.get("symbol") or "").strip()
        and str(row.get("channel") or "").strip()
        and str(row.get("mechanism") or "").strip()
        for row in exposures
    ):
        return False
    what = layers["what_changes"]
    if not str(what.get("invalidation") or "").strip() and not str(what.get("follow_up") or "").strip():
        return False
    return True


def build_causal_chain(
    event: TrustedEvent,
    *,
    fact_text: str,
    fact_excerpt: str,
    fact_refs: list[dict[str, Any]],
    change_text: str,
    change_refs: list[dict[str, Any]],
    direction: str | None,
    horizon: str | None,
    confidence: str | None,
    exposures: list[dict[str, Any]],
    what_text: str,
    invalidation: str | None,
    follow_up: str | None,
    what_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    eid = event.event_id
    fact_id = f"fact:{eid}"
    change_id = f"change:{eid}"
    expectation_id = f"expectation:{eid}"
    impact_id = f"impact:{eid}"
    markets = sorted({str(row.get("channel") or "") for row in exposures if row.get("channel")})
    if exposures:
        impact_text = "先市场/行业：" + (" / ".join(markets) if markets else "市场背景")
        impact_text += "".join(
            f"；{row.get('symbol')} 经 {row.get('channel')}（{row.get('mechanism')}）" for row in exposures
        )
    else:
        impact_text = ""
    exp_direction = direction or "withheld"
    exp_horizon = horizon or event.duration or "unspecified"
    exp_confidence = confidence or "insufficient"
    exp_text = f"方向 {exp_direction} · 期限 {exp_horizon} · 置信度 {exp_confidence}"
    layers = [
        _layer(eid, "fact", fact_text, [], fact_refs, excerpt=fact_excerpt, bound_to="original_text"),
        _layer(eid, "change", change_text, [fact_id], change_refs),
        _layer(
            eid,
            "expectation",
            exp_text,
            [change_id],
            change_refs,
            direction=exp_direction,
            horizon=exp_horizon,
            confidence=exp_confidence,
        ),
        _layer(eid, "impact", impact_text, [expectation_id], [], exposures=list(exposures), markets=markets),
        _layer(
            eid,
            "what_changes",
            what_text,
            [impact_id],
            what_refs,
            invalidation=invalidation or "",
            follow_up=follow_up or "",
        ),
    ]
    chain = {"layers": layers}
    chain["complete"] = causal_chain_is_complete(chain)
    return chain


def _supporting_fact(live_claims: list[EventClaim], fallback_text: str) -> tuple[str, str]:
    for claim in live_claims:
        excerpt = str(claim.excerpt or "")
        if excerpt and excerpt_supports_claim(claim.text, excerpt):
            return claim.text, excerpt
    if live_claims:
        latest = live_claims[-1]
        return latest.text or fallback_text, str(latest.excerpt or "")
    return fallback_text, ""


def analyze_event(event: TrustedEvent, *, symbols: list[str] | None = None) -> dict[str, Any]:
    wanted = [item.upper() for item in (symbols or DISPLAY_SYMBOLS)]
    official_refs = [row for row in _refs(event, facts_only=True) if row["content_type"] == "official_fact"]
    current_official = [row for row in _refs(event, facts_only=True, current_only=True) if row["content_type"] == "official_fact"]
    fact_refs = _refs(event, facts_only=True)
    all_refs = _refs(event)
    opinion_refs = _opinion_refs(event)
    conflicts = _conflicts(event)
    confidence = _confidence(event)
    bound_refs = official_refs or fact_refs or all_refs
    current_refs = current_official or official_refs or bound_refs
    path = evolution_path(event)
    live_claims = sorted(current_claims(event), key=lambda row: row.observed_at or row.valid_from or "")
    latest_claim = live_claims[-1] if live_claims else None
    if event.status == "revoked":
        change = "官方/后续报道撤销或否定先前表述"
        what = "撤销后主结论回到事件发生前的观察状态"
    elif path:
        change = "官方预测基线随事实演化：" + " → ".join(path)
        what = " → ".join(path) + "。旧预测保留在时间线并由后续官方预测替代，不作为当前冲突。"
    elif event.status == "updated":
        change = "同一事件出现后续官方文档，刷新时间线"
        what = "单发布方多文档进入同一时间线，不视为独立多源确认，也不重复叠加一条新方向"
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
            "causal_chain": build_causal_chain(
                event,
                fact_text="",
                fact_excerpt="",
                fact_refs=[],
                change_text="",
                change_refs=[],
                direction="withheld",
                horizon=event.duration,
                confidence="insufficient",
                exposures=[],
                what_text="",
                invalidation=event.invalidation,
                follow_up="",
                what_refs=[],
            ),
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
    invalidation = event.invalidation
    latest_phase = infer_phase(latest_claim.text) if latest_claim else (path[-1] if path else None)
    if (path and path[-1] == "重开/供应恢复") or latest_phase == "reopen_supply":
        direction_hint = "relief"
        horizon = "weeks_to_months"
        invalidation = "若霍尔木兹再次中断或 EIA 撤回供应恢复预测，则该演化失效"
    elif (path and path[-1] == "需求缓冲") or latest_phase == "demand_buffer":
        direction_hint = "watch"
        horizon = "weeks_to_months"
        invalidation = "若需求回升使价格缓冲失效或中断扩大，则该观察失效"
    elif (path and path[-1] == "中断") or latest_phase == "disruption":
        direction_hint = "pressure"
        horizon = "days_to_weeks"
        invalidation = "若官方确认海峡通行恢复或撤回中断预测，则该影响链失效"
    else:
        direction_hint = "pressure" if event.severity in {"high", "critical"} else "watch"
    if confidence in {"insufficient", "revoked"} or not official_refs:
        withheld = _withhold("缺少 Tier 1 官方事实或事件已撤销，不输出方向")
    elif conflicts:
        withheld = _withhold("同一 as-of 窗口存在不同发布方冲突 claim，方向 withhold")
    else:
        withheld = {
            "status": "observable",
            "reason": "可观察传导方向/期限，不是个股交易指令或价格区间",
            "direction": direction_hint,
            "horizon": horizon,
            "percent_forecast": None,
            "price_target": None,
        }
        direction = withheld["direction"]

    confirmed_text, fact_excerpt = _supporting_fact(live_claims, latest_claim.text if latest_claim else event.canonical_title)
    follow_up = "继续观察后续官方文档是否改写该时间线或暴露映射"
    analysis = {
        "confirmed_facts": [
            {
                "text": confirmed_text,
                "evidence_refs": current_refs[:1] or official_refs[:1] or bound_refs[:1],
            }
        ],
        "change_vs_baseline": _bound(change, current_refs or bound_refs),
        "mechanism": _bound(mechanism, official_refs or bound_refs),
        "affected_markets": sorted({row["channel"] for row in exposures}) or ["market_background"],
        "exposures": exposures,
        "direction": _bound(direction, current_refs if direction else []),
        "horizon": _bound(horizon, current_refs or bound_refs),
        "confidence": _bound(confidence, current_refs or bound_refs),
        "counter_evidence": [_bound(row["text"], bound_refs) for row in conflicts]
        + [_bound(invalidation or "", bound_refs)],
        "invalidation": _bound(invalidation, bound_refs),
        "what_changes": _bound(what, current_refs or bound_refs),
        "withheld": withheld,
        "evidence_refs": bound_refs,
        "opinion_refs": opinion_refs,
        "conflict_count": len(conflicts),
        "confidence_rule": confidence_rule(event),
        "evolution_path": path,
        "document_count": confidence_rule(event).get("document_count"),
        "publisher_count": confidence_rule(event).get("publisher_count"),
        "independent_publisher_count": confidence_rule(event).get("independent_publisher_count"),
        "superseded_count": confidence_rule(event).get("superseded_count"),
        "percent_forecast": None,
        "price_target": None,
        "vix_role": "risk_confirmation_only" if event.event_type == "vix_risk" else "not_applicable",
        "causal_chain": build_causal_chain(
            event,
            fact_text=confirmed_text,
            fact_excerpt=fact_excerpt,
            fact_refs=current_refs[:1] or official_refs[:1] or bound_refs[:1],
            change_text=change,
            change_refs=current_refs or bound_refs,
            direction=direction or withheld.get("direction") or "withheld",
            horizon=horizon,
            confidence=confidence,
            exposures=exposures,
            what_text=what,
            invalidation=invalidation,
            follow_up=follow_up,
            what_refs=current_refs or bound_refs,
        ),
        "answers": {
            "what_happened": confirmed_text,
            "credibility": confidence,
            "why_relevant": "市场事件中心完整展示；个股页只保留有暴露映射的事件",
            "how_long": horizon,
            "invalidates_when": invalidation,
        },
    }
    event.coverage = {**(event.coverage or {}), **source_metrics(event.sources, event.claims), "conflict_count": len(conflicts)}
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
