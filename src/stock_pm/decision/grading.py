"""Per-chain graded judgment. One gap degrades its chain, not the whole page."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .causal import (
    CHANNEL_DURATION,
    INFLATION_CAUSE_METRICS,
    RATES_DISCOUNT_MECHANISM,
    CausalImpact,
    MarketConfirmation,
    canonical_metric,
    mechanism_requires_expectation,
)
from .change import ChangeSnapshot
from .expectation import ExpectationGap
from .tension import PriceExpectationTension
from .types import PRICE_METRICS


CHAIN_IDS = ("price", "earnings", "macro_rates", "risk_sentiment")
CHAIN_TITLES = {
    "price": ("Price", "价格"),
    "earnings": ("Earnings", "盈利预期"),
    "macro_rates": ("Macro / Rates", "宏观利率"),
    "risk_sentiment": ("Risk Sentiment", "风险情绪"),
    "news": ("News / Clue", "未确认线索"),
}

# Maps gap codes to the chain/stage they may degrade. Never a page-wide veto.
GAP_EFFECTS: dict[str, dict[str, str]] = {
    "invalid_ohlc": {"chain": "price", "stage": "facts"},
    "missing_price_source": {"chain": "price", "stage": "facts"},
    "invalid_price_ref": {"chain": "price", "stage": "facts"},
    "missing_price_baseline": {"chain": "price", "stage": "change"},
    "missing_earnings": {"chain": "earnings", "stage": "facts"},
    "missing_prior_consensus": {"chain": "earnings", "stage": "expectation"},
    "missing_latest_consensus": {"chain": "earnings", "stage": "expectation"},
    "missing_earnings_as_of": {"chain": "earnings", "stage": "expectation"},
    "missing_macro_baseline": {"chain": "macro_rates", "stage": "change"},
    "missing_cpi": {"chain": "macro_rates", "stage": "what_changed"},
    "missing_rates_confirmation": {"chain": "macro_rates", "stage": "confirmation"},
    "missing_rate_path_expectation": {"chain": "macro_rates", "stage": "expectation"},
    "rates_chain_incomplete": {"chain": "macro_rates", "stage": "tension"},
    "missing_mechanism": {"chain": "macro_rates", "stage": "causal"},
    "missing_exposure": {"chain": "macro_rates", "stage": "causal"},
    "missing_vix": {"chain": "risk_sentiment", "stage": "confirmation"},
    "unverified_news": {"chain": "news", "stage": "causal"},
    "clock_insufficient": {"chain": "page", "stage": "clock"},
    "not_observed": {"chain": "macro_rates", "stage": "facts"},
    "stale_dataset": {"chain": "macro_rates", "stage": "what_changed"},
    "window_mismatch": {"chain": "macro_rates", "stage": "what_changed"},
    "below_materiality": {"chain": "macro_rates", "stage": "change"},
}

NEXT_EVIDENCE = {
    "price": {
        "L0": "补可校验且可追溯的价格 OHLC（source + as_of）",
        "L1": "补可追溯预期与价格/预期张力后，才可能进入局部因果",
        "L2": "补该标的传导机制与暴露后，才可能输出方向性 Thesis",
    },
    "earnings": {
        "L0": "补带 as_of/source 的财报实际值与最新共识",
        "L1": "补最新财报前共识的独立 as_of 与 source，才能比较 surprise",
        "L2": "补前次一致预期（prior consensus + as_of + source），可升级到完整盈利链",
    },
    "macro_rates": {
        "L0": "补可追溯的 CPI/PCE 事实变化",
        "L1": "补利率路径/降息概率的 current vs prior（含 as_of/source）以及市场确认通道",
        "L2": "补个股久期暴露与价格/预期张力后，才可升级到个股 L3；缺 VIX 只限制风险情绪链",
    },
    "risk_sentiment": {
        "L0": "补可追溯 VIX Change（source + as_of）",
        "L1": "补达到重要性阈值的 VIX 变化，才能描述风险偏好",
        "L2": "风险情绪没有独立个股机制，不能单独升级为完整个股方向",
    },
    "news": {
        "L1": "核实来源与事实后，才可能进入因果层；未核实新闻不得改 Thesis",
    },
}


def annotate_gaps(gaps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in gaps or ():
        item = dict(raw)
        code = str(item.get("code") or "")
        meta = GAP_EFFECTS.get(code, {})
        chain = item.get("affects_chain") or meta.get("chain")
        stage = item.get("affects_stage") or meta.get("stage")
        if not chain:
            chain = "macro_rates" if "macro" in code or "cpi" in code or "rate" in code else "page"
        if not stage:
            stage = "unspecified"
        item["affects_chain"] = chain
        item["affects_stage"] = stage
        rows.append(item)
    return rows


def _gaps_for(gaps: list[dict[str, Any]], chain: str) -> list[dict[str, Any]]:
    return [row for row in gaps if row.get("affects_chain") == chain]


def _has_code(gaps: list[dict[str, Any]], *codes: str) -> bool:
    wanted = set(codes)
    return any(row.get("code") in wanted for row in gaps)


def _primary_ref(obj: Any) -> dict[str, Any] | None:
    refs = list(getattr(obj, "fact_refs", ()) or ())
    if not refs:
        return None
    ref = refs[0]
    return {
        "ref_table": ref.ref_table,
        "ref_id": None if ref.ref_id is None else str(ref.ref_id),
        "as_of": ref.as_of,
        "source": ref.source,
        "synthetic": ref.synthetic,
    }


def _chain_payload(
    *,
    chain_id: str,
    level: str,
    scope: str,
    conclusion: str,
    direction: str | None,
    blocking: list[dict[str, Any]],
    stages: list[str],
    ref_obj: Any = None,
) -> dict[str, Any]:
    title_en, title_zh = CHAIN_TITLES[chain_id]
    next_required = None if level == "L3" else NEXT_EVIDENCE.get(chain_id, {}).get(level)
    if level in {"L1", "L2"} and not next_required:
        next_required = NEXT_EVIDENCE.get(chain_id, {}).get("L1") or "补该链缺失的下一层证据"
    ref = _primary_ref(ref_obj) if ref_obj is not None else None
    return {
        "id": chain_id,
        "title": title_en,
        "title_zh": title_zh,
        "level": level,
        "scope": scope,
        "validated_conclusion": conclusion,
        "direction": direction,
        "blocking_gaps": blocking,
        "affected_stages": stages,
        "next_required_evidence": next_required,
        "source": None if ref is None else ref.get("source"),
        "as_of": None if ref is None else ref.get("as_of"),
        "ref": ref,
    }


def _grade_price(
    changes: list[ChangeSnapshot],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking = _gaps_for(gaps, "price")
    prices = [
        row
        for row in changes
        if canonical_metric(row.metric) in PRICE_METRICS and row.scope == "symbol"
    ]
    stages = sorted({row["affects_stage"] for row in blocking})
    if not prices:
        return _chain_payload(
            chain_id="price",
            level="L0",
            scope="fact",
            conclusion="没有可分析的价格事实" if blocking else "本链无价格输入",
            direction=None,
            blocking=blocking,
            stages=stages or ["facts"],
        )
    change = next((row for row in prices if row.materiality == "material"), prices[0])
    conclusion = change.summary or f"{change.metric} {change.previous_value}→{change.current_value}"
    return _chain_payload(
        chain_id="price",
        level="L1",
        scope="fact",
        conclusion=conclusion,
        direction=None,
        blocking=blocking,
        stages=stages or ["change"],
        ref_obj=change,
    )


def _grade_earnings(
    expectations: list[ExpectationGap],
    gaps: list[dict[str, Any]],
    symbol: str,
) -> dict[str, Any]:
    blocking = _gaps_for(gaps, "earnings")
    stages = sorted({row["affects_stage"] for row in blocking})
    eps = [
        row
        for row in expectations
        if canonical_metric(row.metric) in {"eps", "revenue"}
        and (row.subject == symbol or row.scope == "symbol")
    ]
    missing_prior = _has_code(blocking, "missing_prior_consensus")
    if not eps:
        level = "L0"
        conclusion = "没有可追溯的盈利预期事实"
        return _chain_payload(
            chain_id="earnings",
            level=level,
            scope="fact",
            conclusion=conclusion,
            direction=None,
            blocking=blocking,
            stages=stages or ["facts"],
        )
    gap = eps[0]
    surprise_dir = None
    if gap.surprise_pct is not None:
        if gap.surprise_pct > 0:
            surprise_dir = "bullish"
        elif gap.surprise_pct < 0:
            surprise_dir = "bearish"
    has_prior = gap.prior_consensus is not None and gap.prior_consensus_as_of
    complete = gap.status == "ok" and has_prior and gap.latest_consensus is not None
    if complete and not missing_prior:
        return _chain_payload(
            chain_id="earnings",
            level="L3",
            scope="stock",
            conclusion=gap.reason or "盈利预期链完整",
            direction=surprise_dir,
            blocking=[],
            stages=["expectation"],
            ref_obj=gap,
        )
    if gap.status == "ok":
        return _chain_payload(
            chain_id="earnings",
            level="L2",
            scope="stock",
            conclusion=gap.reason or "盈利局部对照成立，但缺少前次共识，不能输出完整 surprise 方向",
            direction=None,
            blocking=blocking,
            stages=stages or ["expectation"],
            ref_obj=gap,
        )
    if gap.actual is not None or gap.latest_consensus is not None:
        return _chain_payload(
            chain_id="earnings",
            level="L1",
            scope="fact",
            conclusion="盈利数字存在，但缺少可追溯 prior/as_of，只能陈述事实、不能比较 surprise",
            direction=None,
            blocking=blocking,
            stages=stages or ["expectation"],
            ref_obj=gap,
        )
    return _chain_payload(
        chain_id="earnings",
        level="L0",
        scope="fact",
        conclusion=gap.reason or "盈利核心事实不可追溯",
        direction=None,
        blocking=blocking,
        stages=stages or ["facts"],
        ref_obj=gap,
    )


def _grade_macro(
    changes: list[ChangeSnapshot],
    expectations: list[ExpectationGap],
    confirmation: MarketConfirmation | None,
    tension: PriceExpectationTension | None,
    impacts: list[CausalImpact],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking = _gaps_for(gaps, "macro_rates")
    stages = sorted({row["affects_stage"] for row in blocking})
    inflation = [
        row
        for row in changes
        if canonical_metric(row.metric) in INFLATION_CAUSE_METRICS
    ]
    rate_exp = next(
        (
            row
            for row in expectations
            if row.status == "ok"
            and canonical_metric(row.metric) in {"cut_odds", "us2y", "real_rate", "fed_funds", "rate_path"}
        ),
        None,
    )
    confirmed = confirmation is not None and confirmation.status == "confirmed"
    tension_ok = tension is not None and tension.tension not in {"insufficient", None, ""}
    stock_impacts = [
        row
        for row in impacts
        if row.status == "valid"
        and row.direction
        and mechanism_requires_expectation(row.mechanism)
        and row.exposure is not None
        and row.exposure.channel == CHANNEL_DURATION
    ]
    has_exposure = any(
        row.exposure is not None and row.exposure.channel == CHANNEL_DURATION
        for row in impacts
        if getattr(row, "mechanism", None) == RATES_DISCOUNT_MECHANISM
    )
    ref_obj = stock_impacts[0] if stock_impacts else (inflation[0] if inflation else rate_exp)

    if not inflation:
        other_macro = [
            row
            for row in changes
            if canonical_metric(row.metric) not in PRICE_METRICS
            and canonical_metric(row.metric) != "vix"
        ]
        if other_macro:
            cause = other_macro[0]
            return _chain_payload(
                chain_id="macro_rates",
                level="L1",
                scope="fact",
                conclusion=cause.summary or "宏观事实变化已成立，但缺少通胀原因与后续传导",
                direction=None,
                blocking=blocking,
                stages=stages or ["what_changed"],
                ref_obj=cause,
            )
        return _chain_payload(
            chain_id="macro_rates",
            level="L0",
            scope="fact",
            conclusion="没有可分析的通胀/宏观原因事实",
            direction=None,
            blocking=blocking,
            stages=stages or ["what_changed"],
            ref_obj=ref_obj,
        )

    cause = inflation[0]
    if stock_impacts and rate_exp is not None and tension_ok and confirmed and has_exposure:
        impact = stock_impacts[0]
        return _chain_payload(
            chain_id="macro_rates",
            level="L3",
            scope="stock",
            conclusion=impact.reason or "通胀→利率→折现率对个股成立",
            direction=impact.direction,
            blocking=[],
            stages=["what_changed", "expectation", "tension", "causal"],
            ref_obj=impact,
        )

    if confirmed or rate_exp is not None:
        scope = "stock" if has_exposure else "factor"
        if not has_exposure:
            scope = "factor"
        conclusion = (
            "利率路径已局部确认，但缺少个股暴露或张力，只能判断估值/因子压力"
            if not has_exposure or not tension_ok
            else "宏观局部因果成立，尚不能输出完整个股方向"
        )
        return _chain_payload(
            chain_id="macro_rates",
            level="L2",
            scope=scope,
            conclusion=conclusion,
            direction=None,
            blocking=blocking,
            stages=stages or ["confirmation", "causal"],
            ref_obj=cause,
        )

    return _chain_payload(
        chain_id="macro_rates",
        level="L1",
        scope="fact",
        conclusion=cause.summary or "宏观事实变化已成立，后续预期/传导不足",
        direction=None,
        blocking=blocking,
        stages=stages or ["what_changed"],
        ref_obj=cause,
    )


def _grade_risk(
    changes: list[ChangeSnapshot],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking = _gaps_for(gaps, "risk_sentiment")
    stages = sorted({row["affects_stage"] for row in blocking})
    vix = [row for row in changes if canonical_metric(row.metric) == "vix"]
    if not vix:
        return _chain_payload(
            chain_id="risk_sentiment",
            level="L0",
            scope="fact",
            conclusion="没有可追溯的风险情绪事实",
            direction=None,
            blocking=blocking,
            stages=stages or ["confirmation"],
        )
    row = vix[0]
    if row.materiality == "material":
        return _chain_payload(
            chain_id="risk_sentiment",
            level="L2",
            scope="factor",
            conclusion=row.summary or "风险情绪出现重大变化",
            direction=None,
            blocking=blocking,
            stages=["change"],
            ref_obj=row,
        )
    return _chain_payload(
        chain_id="risk_sentiment",
        level="L1",
        scope="fact",
        conclusion=row.summary or "观察到 VIX，但未达到重要性阈值",
        direction=None,
        blocking=blocking,
        stages=["change"],
        ref_obj=row,
    )


def _grade_news(clues: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not clues and not _gaps_for(gaps, "news"):
        return None
    blocking = _gaps_for(gaps, "news")
    headline = clues[0].get("headline") if clues else "未确认线索"
    return _chain_payload(
        chain_id="news",
        level="L1",
        scope="fact",
        conclusion=f"未核实新闻仅作线索：{headline}",
        direction=None,
        blocking=blocking,
        stages=["causal"],
    )


def _usable_conclusions(rows: list[dict[str, Any]]) -> list[str]:
    skip = ("缺失", "没有可分析", "核心事实无效", "本链无")
    lines = []
    for row in rows:
        text = str(row.get("validated_conclusion") or "").strip()
        if not text or any(token in text for token in skip):
            continue
        lines.append(text)
    return lines


def _overall(chains: list[dict[str, Any]], *, clock_status: str) -> dict[str, Any]:
    if clock_status == "clock_insufficient":
        return {
            "level": "L0",
            "status": "unavailable",
            "direction": None,
            "can_form_direction": False,
            "can_determine": "没有任何带观察时间的证据",
            "cannot_determine": "无可靠观察时间，不能形成任何链的判断",
            "available_counts": {"L0": len(chains), "L1": 0, "L2": 0, "L3": 0},
        }
    core = [row for row in chains if row["id"] != "news"]
    counts = Counter(row["level"] for row in core)
    l3 = [row for row in core if row["level"] == "L3"]
    dirs = {row["direction"] for row in l3 if row.get("direction") in {"bullish", "bearish"}}
    counts_payload = {
        "L0": int(counts.get("L0", 0)),
        "L1": int(counts.get("L1", 0)),
        "L2": int(counts.get("L2", 0)),
        "L3": int(counts.get("L3", 0)),
    }
    can_bits = _usable_conclusions([row for row in core if row["level"] in {"L1", "L2", "L3"}])
    cannot_bits = [
        row["next_required_evidence"]
        for row in core
        if row["level"] in {"L0", "L1", "L2"} and row.get("next_required_evidence")
    ]
    if len(dirs) > 1:
        return {
            "level": "L3",
            "status": "conflict",
            "direction": None,
            "can_form_direction": False,
            "can_determine": "；".join(can_bits) or "存在完整但方向相反的证据链",
            "cannot_determine": "同等强度的 L3 方向冲突，不能合成统一个股方向",
            "available_counts": counts_payload,
        }
    if l3:
        direction = next(iter(dirs)) if dirs else None
        return {
            "level": "L3",
            "status": "full",
            "direction": direction,
            "can_form_direction": direction in {"bullish", "bearish"},
            "can_determine": "；".join(_usable_conclusions(l3)) or "存在完整证据链",
            "cannot_determine": "；".join(cannot_bits) or "局部缺口不阻止已完整链的方向",
            "available_counts": counts_payload,
        }
    if counts.get("L2"):
        return {
            "level": "L2",
            "status": "partial",
            "direction": None,
            "can_form_direction": False,
            "can_determine": "；".join(_usable_conclusions([row for row in core if row["level"] == "L2"]))
            or "存在局部因果",
            "cannot_determine": "没有 L3，多条 L2 不能堆叠成完整个股方向",
            "available_counts": counts_payload,
        }
    if counts.get("L1"):
        return {
            "level": "L1",
            "status": "fact_only",
            "direction": None,
            "can_form_direction": False,
            "can_determine": "；".join(_usable_conclusions([row for row in core if row["level"] == "L1"]))
            or "存在可追溯事实变化",
            "cannot_determine": "只有事实变化，不能输出方向性 Thesis",
            "available_counts": counts_payload,
        }
    return {
        "level": "L0",
        "status": "unavailable",
        "direction": None,
        "can_form_direction": False,
        "can_determine": "没有可分析的证据链",
        "cannot_determine": "核心事实无效或不可追溯",
        "available_counts": counts_payload,
    }


def grade_decision(
    *,
    symbol: str,
    changes: Iterable[ChangeSnapshot],
    expectations: Iterable[ExpectationGap],
    confirmation: MarketConfirmation | None,
    tension: PriceExpectationTension | None,
    impacts: Iterable[CausalImpact],
    data_gaps: Iterable[dict[str, Any]],
    clues: Iterable[dict[str, Any]] | None = None,
    clock_status: str = "ok",
) -> dict[str, Any]:
    change_rows = list(changes or ())
    expect_rows = list(expectations or ())
    impact_rows = list(impacts or ())
    gaps = annotate_gaps(data_gaps)
    clue_rows = list(clues or ())
    chains = [
        _grade_price(change_rows, gaps),
        _grade_earnings(expect_rows, gaps, symbol),
        _grade_macro(change_rows, expect_rows, confirmation, tension, impact_rows, gaps),
        _grade_risk(change_rows, gaps),
    ]
    news = _grade_news(clue_rows, gaps)
    if news is not None:
        chains.append(news)
    overall = _overall(chains, clock_status=clock_status)
    return {
        "overall": overall,
        "chains": chains,
        "gaps": gaps,
        "can_form_direction": bool(overall["can_form_direction"]),
    }
