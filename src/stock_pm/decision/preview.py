"""Dev/test-only synthetic A/B/C previews. Never used as production fallback."""

from __future__ import annotations

from stock_pm.config import Settings

from .assemble import assemble_from_kernel
from .causal import (
    CHANNEL_DURATION,
    RATES_DISCOUNT_MECHANISM,
    ClaimSource,
    Exposure,
    assess_market_confirmation,
    build_causal_impact,
)
from .change import build_change_snapshot
from .facts import ValidatedFact, require_valid_bar
from .thesis import Driver, build_thesis_snapshot
from .types import FactRef, MaterialityRule


CPI_RULE = MaterialityRule(abs_delta=0.20)
PRICE_RULE = MaterialityRule(pct_delta=2.0)
YIELD_RULE = MaterialityRule(abs_delta=0.05)
ODDS_RULE = MaterialityRule(abs_delta=5.0)
VIX_RULE = MaterialityRule(abs_delta=1.0)
COST_RULE = MaterialityRule(abs_delta=2.0)

PREVIEW_LABELS = {
    "A": "已确认宏观链（合成演示数据）",
    "B": "未确认事件（合成演示数据）",
    "C": "无重大变化（合成演示数据）",
}


def preview_allowed(settings: Settings | None = None) -> bool:
    env = (settings or Settings()).app_env
    return env not in {"production", "prod"}


def _ref(table: str, ref_id: str, as_of: str = "2026-09-10") -> FactRef:
    return FactRef(ref_table=table, ref_id=ref_id, as_of=as_of, source="synthetic", synthetic=True)


def _macro(metric: str, previous: float, current: float, rule: MaterialityRule, as_of: str = "2026-09-10") -> object:
    refs = (_ref("synthetic_series", metric, as_of),)
    return build_change_snapshot(
        metric=metric,
        previous_value=previous,
        current_value=current,
        previous_as_of="2026-09-09" if as_of == "2026-09-10" else "2026-09-08",
        current_as_of=as_of,
        comparison_window="1d",
        materiality_rule=rule,
        fact_refs=refs,
        synthetic=True,
    )


def _company(symbol: str, metric: str, previous: float, current: float, rule: MaterialityRule) -> object:
    refs = (_ref("synthetic_series", f"{symbol}-{metric}"),)
    return build_change_snapshot(
        metric=metric,
        current_fact=ValidatedFact(
            metric=metric, value=current, as_of="2026-09-10", refs=refs, subject=symbol, synthetic=True
        ),
        previous_fact=ValidatedFact(
            metric=metric, value=previous, as_of="2026-09-09", refs=refs, subject=symbol, synthetic=True
        ),
        comparison_window="1d",
        materiality_rule=rule,
        synthetic=True,
    )


def _price(symbol: str, previous: float, current: float) -> object:
    prev = require_valid_bar(
        {
            "open": previous,
            "high": previous,
            "low": previous,
            "close": previous,
            "as_of": "2026-09-09",
            "symbol": symbol,
            "synthetic": True,
        },
        refs=(_ref("daily_price_bars", f"{symbol}-prev", "2026-09-09"),),
    )
    curr = require_valid_bar(
        {
            "open": current,
            "high": current,
            "low": current,
            "close": current,
            "as_of": "2026-09-10",
            "symbol": symbol,
            "synthetic": True,
        },
        refs=(_ref("daily_price_bars", f"{symbol}-curr"),),
    )
    return build_change_snapshot(
        metric="close",
        current_bar=curr,
        previous_bar=prev,
        comparison_window="1d",
        materiality_rule=PRICE_RULE,
        synthetic=True,
    )


def _rates_confirmation(*, hot: bool):
    if hot:
        series = (
            _macro("us2y", 4.00, 4.12, YIELD_RULE),
            _macro("real_rate", 1.50, 1.62, YIELD_RULE),
            _macro("cut_odds", 42.0, 28.0, ODDS_RULE),
        )
    else:
        series = (
            _macro("us2y", 4.00, 4.01, YIELD_RULE),
            _macro("real_rate", 1.50, 1.51, YIELD_RULE),
            _macro("cut_odds", 42.0, 41.5, ODDS_RULE),
            _macro("vix", 16.0, 16.2, VIX_RULE),
        )
    return assess_market_confirmation(path="rates_tightening", series=series, synthetic=True)


def build_preview(symbol: str, scenario: str) -> dict:
    key = (scenario or "").strip().upper()
    if key not in PREVIEW_LABELS:
        raise ValueError("preview must be A, B, or C")
    symbol = (symbol or "NVDA").upper()
    if key == "A":
        return _preview_a(symbol)
    if key == "B":
        return _preview_b(symbol)
    return _preview_c(symbol)


def _preview_a(symbol: str) -> dict:
    cpi = _macro("cpi", 3.0, 3.5, CPI_RULE)
    confirmation = _rates_confirmation(hot=True)
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target=symbol,
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmation,
        synthetic=True,
    )
    price = _price(symbol, 100.0, 104.0)
    stamp = "2026-09-10T16:00:00+00:00"
    previous = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("份额叙事仍在", based_on=(price.id,)),),
        bear_drivers=(Driver("利率路径转鹰", based_on=(impact.id,)),),
        key_disagreement="增长能否消化估值",
        invalidation="实际利率继续上行",
        changes=(price, cpi),
        impacts=(impact,),
        generated_at="2026-09-09T16:00:00+00:00",
        synthetic=True,
    )
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格仍强于基本面节奏", based_on=(price.id,)),),
        bear_drivers=(Driver("通胀→利率→折现率，高估值短期承压", based_on=(impact.id,)),),
        key_disagreement="增长能否消化折现率上行",
        invalidation="实际利率回落或估值压缩结束",
        changes=(price, cpi),
        impacts=(impact,),
        generated_at=stamp,
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[cpi, price],
        expectations=[],
        confirmation=confirmation,
        impacts=[impact],
        thesis=thesis,
        previous_thesis=previous,
        data_gaps=[{"code": "missing_prior_consensus", "text": "本预览只覆盖宏观链，不构造财报共识"}],
        facts=[
            {"kind": "macro", "metric": "cpi", "as_of": cpi.current_as_of, "source": "synthetic", "ref": {"ref_table": "synthetic_series", "ref_id": "cpi", "as_of": cpi.current_as_of, "source": "synthetic"}},
            {"kind": "bar", "metric": "close", "subject": symbol, "as_of": price.current_as_of, "source": "synthetic", "ref": {"ref_table": "daily_price_bars", "ref_id": f"{symbol}-curr", "as_of": price.current_as_of, "source": "synthetic"}},
        ],
        synthetic=True,
        preview="A",
        as_of=cpi.current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["A"]
    return view


def _preview_b(symbol: str) -> dict:
    price = _price(symbol, 100.0, 104.0)
    cost = _company(symbol, "opex", 20.0, 28.0, COST_RULE)
    rumor = build_causal_impact(
        cause=_macro("geopolitics_headline", 0, 1, MaterialityRule(abs_delta=1)),
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target=symbol, target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=assess_market_confirmation(path="rates_tightening", series=(), synthetic=True),
        claim=ClaimSource(source_class="social", verified=False, text="synthetic unverified war/sanctions rumor"),
        synthetic=True,
    )
    stamp = "2026-09-10T16:05:00+00:00"
    previous = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格仍强", based_on=(price.id,)),),
        bear_drivers=(Driver("费用上升", based_on=(cost.id,)),),
        key_disagreement="费用能否被收入消化",
        invalidation="费用继续上行且份额走弱",
        changes=(price, cost),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格仍强", based_on=(price.id,)),),
        bear_drivers=(Driver("费用上升", based_on=(cost.id,)),),
        key_disagreement="费用能否被收入消化",
        invalidation="费用继续上行且份额走弱",
        changes=(price, cost),
        impacts=(rumor,),
        generated_at=stamp,
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[price, cost],
        expectations=[],
        confirmation=rumor.market_confirmation,
        impacts=[rumor],
        thesis=thesis,
        previous_thesis=previous,
        data_gaps=[{"code": "unverified_news", "text": "未核实战争/制裁传闻只能作为线索，不改变 Thesis"}],
        facts=[],
        clues=[
            {
                "status": "unverified",
                "headline": "synthetic unverified war/sanctions rumor",
                "source": "synthetic",
                "ref": {
                    "ref_table": "synthetic_news",
                    "ref_id": "war-sanctions-rumor",
                    "as_of": "2026-09-10",
                    "source": "synthetic",
                },
                "as_of": "2026-09-10",
                "why": "未核实新闻只能作为线索，不改变 Thesis",
            }
        ],
        synthetic=True,
        preview="B",
        as_of=price.current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["B"]
    return view


def _preview_c(symbol: str) -> dict:
    tiny = (
        _macro("cpi", 3.00, 3.02, CPI_RULE),
        _macro("us2y", 4.00, 4.01, YIELD_RULE),
        _macro("vix", 16.0, 16.1, VIX_RULE),
    )
    confirmation = assess_market_confirmation(path="rates_tightening", series=tiny[1:], synthetic=True)
    stamp = "2026-09-10T16:00:00+00:00"
    previous = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("需求稳定", based_on=()),),
        bear_drivers=(Driver("估值不便宜", based_on=()),),
        key_disagreement="估值",
        invalidation="需求失速",
        generated_at="2026-09-09T16:00:00+00:00",
        synthetic=True,
    )
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("需求稳定", based_on=()),),
        bear_drivers=(Driver("估值不便宜", based_on=()),),
        key_disagreement="估值",
        invalidation="需求失速",
        changes=tiny,
        generated_at=stamp,
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=list(tiny),
        expectations=[],
        confirmation=confirmation,
        impacts=[],
        thesis=thesis,
        previous_thesis=previous,
        data_gaps=[
            {"code": "below_materiality", "text": "全低于重要性阈值"},
            {"code": "missing_rates_confirmation", "text": "利率路径未确认"},
        ],
        facts=[],
        synthetic=True,
        preview="C",
        as_of=tiny[0].current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["C"]
    return view
