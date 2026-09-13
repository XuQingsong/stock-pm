"""Dev/test-only synthetic A/B/C previews. Opt-in; never a production fallback."""

from __future__ import annotations

import os

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
from .expectation import ExpectationPoint, build_expectation_gap
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
    "L0": "L0 不可用（合成演示数据）",
    "L1": "L1 仅事实（合成演示数据）",
    "L2": "L2 局部判断（合成演示数据）",
    "L3": "L3 完整方向（合成演示数据）",
    "CONFLICT": "L3 方向冲突（合成演示数据）",
}


PREVIEW_ENV_ALLOWLIST = frozenset({"development", "test", "local"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def preview_allowed(settings: Settings | None = None) -> bool:
    """Explicit dual opt-in. Missing APP_ENV is not treated as development."""
    if settings is None:
        enabled = _truthy(os.getenv("ENABLE_DECISION_PREVIEW"))
        env = (os.getenv("APP_ENV") or "").strip().lower()
    else:
        enabled = bool(settings.enable_decision_preview)
        env = (settings.app_env or "").strip().lower()
    return enabled and env in PREVIEW_ENV_ALLOWLIST


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
        raise ValueError("preview must be A, B, C, L0, L1, L2, L3, or CONFLICT")
    symbol = (symbol or "NVDA").upper()
    if key == "A":
        return _preview_a(symbol)
    if key == "B":
        return _preview_b(symbol)
    if key == "C":
        return _preview_c(symbol)
    if key == "L0":
        return _preview_l0(symbol)
    if key == "L1":
        return _preview_l1(symbol)
    if key == "L2":
        return _preview_l2(symbol)
    if key == "L3":
        view = build_preview_a(symbol)
        view["preview"] = "L3"
        view["preview_label"] = PREVIEW_LABELS["L3"]
        return view
    return _preview_conflict(symbol)


def _rate_path_expectation() -> object:
    prior_ref = _ref("synthetic_series", "cut_odds-prior", "2026-09-09")
    latest_ref = _ref("synthetic_series", "cut_odds", "2026-09-10")
    return build_expectation_gap(
        metric="cut_odds",
        fiscal_period="fomc-path-2026-09",
        prior_consensus=ExpectationPoint(
            value=42.0,
            as_of="2026-09-09",
            source="synthetic",
            currency=None,
            basis="unknown",
            fact_ref=prior_ref,
            synthetic=True,
        ),
        latest_consensus=ExpectationPoint(
            value=28.0,
            as_of="2026-09-10",
            source="synthetic",
            currency=None,
            basis="unknown",
            fact_ref=latest_ref,
            synthetic=True,
        ),
        synthetic=True,
    )


def _preview_a(symbol: str) -> dict:
    return build_preview_a(symbol)


def build_preview_a(
    symbol: str,
    *,
    include_expectation: bool = True,
    include_price: bool = True,
    previous_close: float = 100.0,
    current_close: float = 104.0,
) -> dict:
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
    price = _price(symbol, previous_close, current_close) if include_price else None
    expectation = _rate_path_expectation() if include_expectation else None
    stamp = "2026-09-10T16:00:00+00:00"
    changes = [cpi] + ([price] if price is not None else [])
    expectations = [expectation] if expectation is not None else []
    previous = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("份额叙事仍在", based_on=((price.id,) if price is not None else (cpi.id,))),),
        bear_drivers=(Driver("利率路径转鹰", based_on=(impact.id,)),),
        key_disagreement="增长能否消化估值",
        invalidation="实际利率继续上行",
        changes=tuple(changes),
        expectations=tuple(expectations),
        impacts=(impact,),
        generated_at="2026-09-09T16:00:00+00:00",
        synthetic=True,
    )
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格仍强于基本面节奏", based_on=((price.id,) if price is not None else (cpi.id,))),),
        bear_drivers=(Driver("通胀→利率→折现率，高估值短期承压", based_on=(impact.id,)),),
        key_disagreement="增长能否消化折现率上行",
        invalidation="实际利率回落或估值压缩结束",
        changes=tuple(changes),
        expectations=tuple(expectations),
        impacts=(impact,),
        generated_at=stamp,
        synthetic=True,
    )
    gaps = [
        {
            "code": "missing_prior_consensus",
            "text": "本预览不构造财报 EPS 共识；利率路径预期见 Expectation Change",
        }
    ]
    if not include_expectation:
        gaps = [
            {
                "code": "missing_rate_path_expectation",
                "text": "删除利率路径预期后，不能把通胀变化写成有效空头驱动",
            }
        ]
    facts = [
        {
            "kind": "macro",
            "metric": "cpi",
            "as_of": cpi.current_as_of,
            "source": "synthetic",
            "ref": {
                "ref_table": "synthetic_series",
                "ref_id": "cpi",
                "as_of": cpi.current_as_of,
                "source": "synthetic",
            },
        },
    ]
    if price is not None:
        facts.append(
            {
                "kind": "bar",
                "metric": "close",
                "subject": symbol,
                "as_of": price.current_as_of,
                "source": "synthetic",
                "ref": {
                    "ref_table": "daily_price_bars",
                    "ref_id": f"{symbol}-curr",
                    "as_of": price.current_as_of,
                    "source": "synthetic",
                },
            }
        )
    if expectation is not None:
        facts.append(
            {
                "kind": "expectation",
                "metric": "cut_odds",
                "as_of": expectation.latest_consensus_as_of,
                "source": "synthetic",
                "ref": {
                    "ref_table": "synthetic_series",
                    "ref_id": "cut_odds",
                    "as_of": expectation.latest_consensus_as_of,
                    "source": "synthetic",
                },
            }
        )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=changes,
        expectations=expectations,
        confirmation=confirmation,
        impacts=[impact],
        thesis=thesis,
        previous_thesis=previous,
        data_gaps=gaps,
        facts=facts,
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


def _eps_gap(symbol: str):
    prior_ref = _ref("earnings_reports", f"{symbol}-eps-prior", "2026-07-13")
    latest_ref = _ref("earnings_reports", f"{symbol}-eps-latest", "2026-08-11")
    actual_ref = _ref("earnings_reports", f"{symbol}-eps-actual", "2026-08-12")
    return build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=ExpectationPoint(
            value=1.18,
            as_of="2026-07-13",
            source="street",
            currency="USD",
            basis="gaap",
            fact_ref=prior_ref,
            subject=symbol,
            fiscal_period="FY2026Q2",
            synthetic=True,
        ),
        latest_consensus=ExpectationPoint(
            value=1.28,
            as_of="2026-08-11",
            source="street",
            currency="USD",
            basis="gaap",
            fact_ref=latest_ref,
            subject=symbol,
            fiscal_period="FY2026Q2",
            synthetic=True,
        ),
        actual=ExpectationPoint(
            value=1.30,
            as_of="2026-08-12",
            source="company",
            currency="USD",
            basis="gaap",
            fact_ref=actual_ref,
            subject=symbol,
            fiscal_period="FY2026Q2",
            synthetic=True,
        ),
        synthetic=True,
    )


def _preview_l0(symbol: str) -> dict:
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("无可用观察", based_on=()),),
        bear_drivers=(Driver("无可用观察", based_on=()),),
        key_disagreement="没有观察时间",
        invalidation="出现带 as_of 的事实",
        generated_at="1970-01-01T00:00:00+00:00",
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[],
        expectations=[],
        confirmation=None,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[
            {
                "code": "clock_insufficient",
                "text": "无可靠观察时间，不能猜测今天或用未来事件日代替，目前不能形成判断",
            }
        ],
        facts=[],
        synthetic=True,
        preview="L0",
        as_of=None,
        clock_status="clock_insufficient",
    )
    view["preview_label"] = PREVIEW_LABELS["L0"]
    return view


def _preview_l1(symbol: str) -> dict:
    price = _price(symbol, 100.0, 104.0)
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格上升且达到重要性阈值", based_on=(price.id,)),),
        bear_drivers=(),
        key_disagreement="尚无合格反方",
        invalidation="价格回吐该变动",
        changes=(price,),
        generated_at="2026-09-10T16:00:00+00:00",
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[price],
        expectations=[],
        confirmation=None,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[
            {"code": "missing_cpi", "text": "缺失 CPI/PCE 原因序列"},
            {"code": "missing_vix", "text": "缺失 VIX"},
            {"code": "missing_prior_consensus", "text": "缺失前次一致预期"},
        ],
        facts=[
            {
                "kind": "bar",
                "metric": "close",
                "subject": symbol,
                "as_of": price.current_as_of,
                "source": "synthetic",
                "ref": {
                    "ref_table": "daily_price_bars",
                    "ref_id": f"{symbol}-curr",
                    "as_of": price.current_as_of,
                    "source": "synthetic",
                },
            }
        ],
        synthetic=True,
        preview="L1",
        as_of=price.current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["L1"]
    return view


def _preview_l2(symbol: str) -> dict:
    cpi = _macro("cpi", 3.0, 3.5, CPI_RULE)
    confirmation = _rates_confirmation(hot=True)
    expectation = _rate_path_expectation()
    price = _price(symbol, 100.0, 104.0)
    stamp = "2026-09-10T16:00:00+00:00"
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("价格仍强于基本面节奏", based_on=(price.id,)),),
        bear_drivers=(Driver("费用观察中", based_on=(price.id,)),),
        key_disagreement="利率压力是否传到个股",
        invalidation="确认路径反转",
        changes=(cpi, price),
        expectations=(expectation,),
        generated_at=stamp,
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[cpi, price],
        expectations=[expectation],
        confirmation=confirmation,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[
            {"code": "missing_vix", "text": "缺失 VIX"},
            {"code": "missing_exposure", "text": "该标的没有利率久期暴露，不把宏观直接写成个股方向"},
            {"code": "missing_prior_consensus", "text": "缺失前次一致预期"},
        ],
        facts=[],
        synthetic=True,
        preview="L2",
        as_of=cpi.current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["L2"]
    return view


def _preview_conflict(symbol: str) -> dict:
    return _preview_conflict_from_parts(symbol, _eps_gap(symbol))


def _preview_conflict_from_parts(symbol: str, eps) -> dict:
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
    expectation = _rate_path_expectation()
    stamp = "2026-09-10T16:00:00+00:00"
    thesis = build_thesis_snapshot(
        symbol=symbol,
        bull_drivers=(Driver("EPS 相对最新共识为正", based_on=(eps.id,)),),
        bear_drivers=(Driver("通胀→利率→折现率，高估值短期承压", based_on=(impact.id,)),),
        key_disagreement="盈利改善是否已被折现率上行对冲",
        invalidation="利率回落或盈利下修",
        changes=(price, cpi),
        expectations=(expectation, eps),
        impacts=(impact,),
        generated_at=stamp,
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol=symbol,
        changes=[cpi, price],
        expectations=[expectation, eps],
        confirmation=confirmation,
        impacts=[impact],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[{"code": "missing_vix", "text": "缺失 VIX"}],
        facts=[],
        synthetic=True,
        preview="CONFLICT",
        as_of=cpi.current_as_of,
    )
    view["preview_label"] = PREVIEW_LABELS["CONFLICT"]
    return view

