"""Golden tests A–S for Investment Decision Kernel v1.

All fixtures in this module are synthetic. They are not live market prints.
"""

from __future__ import annotations

import pytest

from stock_pm.decision import (
    CHANNEL_COMMODITY_REVENUE,
    CHANNEL_DURATION,
    CHANNEL_FUEL_COST,
    Driver,
    FactRef,
    FactValidationError,
    MaterialityRule,
    NO_MATERIAL_CHANGE_THESIS,
    OIL_CONSUMER_MECHANISM,
    OIL_PRODUCER_MECHANISM,
    RATES_DISCOUNT_MECHANISM,
    UNCONFIRMED,
    ClaimSource,
    ExpectationPoint,
    Exposure,
    assess_market_confirmation,
    build_causal_impact,
    build_change_snapshot,
    build_expectation_gap,
    build_price_expectation_tension,
    build_thesis_snapshot,
    build_what_changed,
    require_valid_bar,
    validate_ohlc,
)

SYNTHETIC = True

CPI_RULE = MaterialityRule(abs_delta=0.20)
YIELD_RULE = MaterialityRule(abs_delta=0.05)  # 5bp if yield is in percent
ODDS_RULE = MaterialityRule(abs_delta=5.0)
VIX_RULE = MaterialityRule(abs_delta=1.0)
OIL_RULE = MaterialityRule(pct_delta=3.0)
PE_RULE = MaterialityRule(pct_delta=5.0)


def _ref(table: str, ref_id: str) -> FactRef:
    return FactRef(ref_table=table, ref_id=ref_id, as_of="2026-09-10", source="synthetic", synthetic=True)


def _chg(metric: str, previous, current, *, rule: MaterialityRule, window: str = "1d"):
    return build_change_snapshot(
        metric=metric,
        previous_value=previous,
        current_value=current,
        previous_as_of="2026-09-09",
        current_as_of="2026-09-10",
        comparison_window=window,
        materiality_rule=rule,
        fact_refs=(_ref("synthetic_series", metric),),
        synthetic=True,
    )


def _eps(value, as_of, *, period=None, source="street", basis="gaap"):
    return ExpectationPoint(
        value=value,
        as_of=as_of,
        source=source,
        currency="USD",
        basis=basis,
        fiscal_period=period,
        synthetic=True,
    )


def _oil_producer():
    oil = _chg("wti", 70.0, 77.0, rule=OIL_RULE)
    impact = build_causal_impact(
        cause=oil,
        mechanism=OIL_PRODUCER_MECHANISM,
        exposure=Exposure(target="XOM", target_kind="company", channel=CHANNEL_COMMODITY_REVENUE),
        market_confirmation=assess_market_confirmation(path="none", series=(), synthetic=True),
        synthetic=True,
    )
    return oil, impact


# ---------------------------------------------------------------------------
# A
# ---------------------------------------------------------------------------

def test_A_cpi_slight_unconfirmed_no_tech_bearish_causal():
    cpi = _chg("cpi", 3.0, 3.1, rule=CPI_RULE)
    us2y = _chg("us2y", 4.00, 4.01, rule=YIELD_RULE)
    real_rate = _chg("real_rate", 1.50, 1.51, rule=YIELD_RULE)
    cut_odds = _chg("cut_odds", 42.0, 41.5, rule=ODDS_RULE)
    vix = _chg("vix", 16.0, 16.2, rule=VIX_RULE)
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(us2y, real_rate, cut_odds, vix),
        synthetic=True,
    )
    assert confirmation.status == "unconfirmed"
    assert UNCONFIRMED in confirmation.reason

    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target="NVDA",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmation,
        synthetic=True,
    )
    assert impact.status == "unconfirmed"
    assert impact.direction is None
    assert UNCONFIRMED in impact.reason
    assert "高估值" not in "".join(impact.chain)


# ---------------------------------------------------------------------------
# B
# ---------------------------------------------------------------------------

def test_B_cpi_hot_confirmed_duration_chain():
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    us2y = _chg("us2y", 4.00, 4.12, rule=YIELD_RULE)
    real_rate = _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE)
    cut_odds = _chg("cut_odds", 42.0, 28.0, rule=ODDS_RULE)
    assert us2y.delta == pytest.approx(0.12)
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(us2y, real_rate, cut_odds),
        synthetic=True,
    )
    assert confirmation.status == "confirmed"
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target="AVGO",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmation,
        synthetic=True,
    )
    assert impact.status == "valid"
    assert impact.direction == "bearish"
    assert impact.chain == ("通胀", "利率路径", "折现率", "高估值成长短期承压")


# ---------------------------------------------------------------------------
# C
# ---------------------------------------------------------------------------

def test_C_eps_revision_and_surprise_not_slogan():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=ExpectationPoint(
            value=1.18,
            as_of="2026-07-13",
            source="street",
            currency="USD",
            basis="gaap",
            fact_ref=_ref("consensus", "prior"),
            analyst_count=18,
            synthetic=True,
        ),
        latest_consensus=ExpectationPoint(
            value=1.28,
            as_of="2026-08-11",
            source="street",
            currency="USD",
            basis="gaap",
            fact_ref=_ref("consensus", "latest"),
            analyst_count=21,
            synthetic=True,
        ),
        actual=ExpectationPoint(
            value=1.30,
            as_of="2026-08-12",
            source="company",
            currency="USD",
            basis="gaap",
            fact_ref=_ref("earnings_reports", "print"),
            synthetic=True,
        ),
        synthetic=True,
    )
    assert gap.status == "ok"
    assert gap.revision_pct == pytest.approx(8.47, abs=0.01)
    assert gap.surprise_pct == pytest.approx(1.56, abs=0.01)
    assert gap.revision_trend == "up"
    assert "超预期利好" not in gap.reason
    assert gap.currency == "USD"
    assert gap.basis == "gaap"


# ---------------------------------------------------------------------------
# D
# ---------------------------------------------------------------------------

def test_D_price_ahead_of_fundamentals():
    pe = _chg("pe", 31.0, 36.0, rule=PE_RULE)
    tension = build_price_expectation_tension(
        fundamentals_change=7.6,
        price_change=22.0,
        valuation_change=pe,
        synthetic=True,
    )
    assert tension.fundamentals_change == pytest.approx(7.6)
    assert tension.price_change == pytest.approx(22.0)
    assert tension.valuation_change == pytest.approx((36 / 31 - 1) * 100, abs=0.05)
    assert tension.tension == "price_ahead_of_fundamentals"
    assert "priced_in" not in tension.to_dict()


# ---------------------------------------------------------------------------
# E
# ---------------------------------------------------------------------------

def test_E_oil_up_splits_by_exposure_and_blocks_tech_without_rates():
    oil = _chg("wti", 70.0, 77.0, rule=OIL_RULE)
    energy = build_causal_impact(
        cause=oil,
        mechanism=OIL_PRODUCER_MECHANISM,
        exposure=Exposure(target="XOM", target_kind="company", channel=CHANNEL_COMMODITY_REVENUE),
        market_confirmation=assess_market_confirmation(path="none", series=(), synthetic=True),
        synthetic=True,
    )
    airline = build_causal_impact(
        cause=oil,
        mechanism=OIL_CONSUMER_MECHANISM,
        exposure=Exposure(target="DAL", target_kind="company", channel=CHANNEL_FUEL_COST),
        market_confirmation=assess_market_confirmation(path="none", series=(), synthetic=True),
        synthetic=True,
    )
    tech_via_oil = build_causal_impact(
        cause=oil,
        mechanism=OIL_PRODUCER_MECHANISM,
        exposure=Exposure(
            target="NVDA",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=assess_market_confirmation(path="none", series=(), synthetic=True),
        synthetic=True,
    )
    assert energy.status == "valid" and energy.direction == "bullish"
    assert airline.status == "valid" and airline.direction == "bearish"
    assert tech_via_oil.direction is None
    assert tech_via_oil.status != "valid"

    unconfirmed_rates = assess_market_confirmation(
        path="rates_tightening",
        series=(_chg("us2y", 4.00, 4.01, rule=YIELD_RULE),),
        synthetic=True,
    )
    tech_unconfirmed = build_causal_impact(
        cause=_chg("cpi", 3.0, 3.5, rule=CPI_RULE),
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=unconfirmed_rates,
        synthetic=True,
    )
    assert tech_unconfirmed.direction is None

    confirmed_rates = assess_market_confirmation(
        path="rates_tightening",
        series=(
            _chg("us2y", 4.00, 4.12, rule=YIELD_RULE),
            _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE),
            _chg("cut_odds", 40.0, 25.0, rule=ODDS_RULE),
        ),
        synthetic=True,
    )
    tech_confirmed = build_causal_impact(
        cause=_chg("cpi", 3.0, 3.5, rule=CPI_RULE),
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target="NVDA",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmed_rates,
        synthetic=True,
    )
    assert tech_confirmed.status == "valid"
    assert tech_confirmed.direction == "bearish"


# ---------------------------------------------------------------------------
# F
# ---------------------------------------------------------------------------

def test_F_unverified_social_war_news_does_not_move_thesis():
    previous = build_thesis_snapshot(
        bull_drivers=("长期需求仍在",),
        bear_drivers=("估值偏贵",),
        key_disagreement="增长能否消化估值",
        invalidation="需求连续两个季度走弱",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    rumor = build_causal_impact(
        cause=_chg("geopolitics_headline", 0, 1, rule=MaterialityRule(abs_delta=1)),
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=assess_market_confirmation(path="rates_tightening", series=(), synthetic=True),
        claim=ClaimSource(
            source_class="social",
            verified=False,
            text="synthetic unverified war/sanctions rumor",
        ),
        synthetic=True,
    )
    assert rumor.status in {"unverified", "insufficient"}
    assert rumor.direction is None
    current = build_thesis_snapshot(
        bull_drivers=("长期需求仍在",),
        bear_drivers=("估值偏贵",),
        key_disagreement="增长能否消化估值",
        invalidation="需求连续两个季度走弱",
        impacts=(rumor,),
        generated_at="2026-09-10T12:05:00+00:00",
        synthetic=True,
    )
    changed = build_what_changed(
        impacts=(rumor,),
        previous_thesis=previous,
        current_thesis=current,
        synthetic=True,
    )
    assert changed.thesis_changed is False
    assert current.direction in {"neutral", "incomplete"} or current.direction == previous.direction


# ---------------------------------------------------------------------------
# G
# ---------------------------------------------------------------------------

def test_G_conflict_keeps_both_sides_no_forced_direction():
    thesis = build_thesis_snapshot(
        bull_drivers=("毛利率扩张", "回购仍在"),
        bear_drivers=("倍数压缩", "利率路径转鹰"),
        key_disagreement="基本面改善是否已被估值扩张对冲",
        invalidation="毛利率下修或实际利率继续上行",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert thesis.direction in {"neutral", "incomplete"}
    assert len(thesis.bear_drivers) >= 1
    assert len(thesis.bull_drivers) >= 1
    assert thesis.direction not in {"bullish", "bearish"}


# ---------------------------------------------------------------------------
# H
# ---------------------------------------------------------------------------

def test_H_below_materiality_is_no_material_change():
    tiny = (
        _chg("cpi", 3.00, 3.02, rule=CPI_RULE),
        _chg("us2y", 4.00, 4.01, rule=YIELD_RULE),
        _chg("vix", 16.0, 16.1, rule=VIX_RULE),
    )
    assert all(row.materiality == "immaterial" for row in tiny)
    previous = build_thesis_snapshot(
        bull_drivers=("需求稳定",),
        bear_drivers=("估值不便宜",),
        key_disagreement="估值",
        invalidation="需求失速",
        generated_at="2026-09-09T12:00:00+00:00",
        synthetic=True,
    )
    current = build_thesis_snapshot(
        bull_drivers=("需求稳定",),
        bear_drivers=("估值不便宜",),
        key_disagreement="估值",
        invalidation="需求失速",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    report = build_what_changed(
        changes=tiny,
        previous_thesis=previous,
        current_thesis=current,
        synthetic=True,
    )
    assert report.summary == NO_MATERIAL_CHANGE_THESIS
    assert report.items == ()
    assert report.thesis_changed is False
    assert all("新闻" not in item.what for item in report.items)


# ---------------------------------------------------------------------------
# I
# ---------------------------------------------------------------------------

def test_I_missing_prior_consensus_has_no_revision_trend():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=ExpectationPoint(
            value=1.28,
            as_of="2026-08-11",
            source="street",
            currency="USD",
            basis="gaap",
            synthetic=True,
        ),
        actual=ExpectationPoint(
            value=1.30,
            as_of="2026-08-12",
            source="company",
            currency="USD",
            basis="gaap",
            synthetic=True,
        ),
        synthetic=True,
    )
    assert gap.revision_pct is None
    assert gap.revision_trend is None
    assert "revision trend" in gap.reason


# ---------------------------------------------------------------------------
# J
# ---------------------------------------------------------------------------

def test_J_invalid_ohlc_cannot_enter_later_layers():
    bad = {"open": 10.0, "high": 9.5, "low": 10.2, "close": 10.1, "synthetic": True}
    check = validate_ohlc(bad)
    assert check.ok is False
    assert check.errors
    with pytest.raises(FactValidationError):
        require_valid_bar(bad)
    with pytest.raises(TypeError, match="ValidatedBar"):
        build_change_snapshot(
            metric="close",
            previous_value=10.0,
            current_value=10.1,
            previous_as_of="2026-09-09",
            current_as_of="2026-09-10",
            synthetic=True,
        )
    prev = require_valid_bar(
        {"open": 9.8, "high": 10.0, "low": 9.7, "close": 10.0, "as_of": "2026-09-09", "synthetic": True}
    )
    curr = require_valid_bar(
        {"open": 10.0, "high": 10.3, "low": 9.9, "close": 10.2, "as_of": "2026-09-10", "synthetic": True}
    )
    ok = build_change_snapshot(
        metric="close",
        current_bar=curr,
        previous_bar=prev,
        comparison_window="1d",
        materiality_rule=MaterialityRule(pct_delta=1.0),
        synthetic=True,
    )
    assert isinstance(prev.close, float)
    assert ok.current_value == pytest.approx(10.2)
    assert ok.previous_value == pytest.approx(10.0)
    assert ok.direction == "up"


def test_missing_baseline_is_not_zero_and_not_a_rise():
    row = build_change_snapshot(
        metric="eps",
        previous_value=None,
        current_value=1.30,
        previous_as_of=None,
        current_as_of="2026-08-12",
        synthetic=True,
    )
    assert row.previous_value is None
    assert row.delta is None
    assert row.delta_pct is None
    assert row.direction == "unknown"
    assert "不能声称上升" in row.summary
    assert row.summary.startswith("无比较基准")


def test_gaap_vs_nongaap_is_conflict_not_a_choice():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=ExpectationPoint(
            value=1.28, as_of="2026-08-11", source="street", currency="USD", basis="gaap", synthetic=True
        ),
        actual=ExpectationPoint(
            value=1.45, as_of="2026-08-12", source="company", currency="USD", basis="non-gaap", synthetic=True
        ),
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.surprise_pct is None


# ---------------------------------------------------------------------------
# K / L / M  (P0-2)
# ---------------------------------------------------------------------------

def test_K_latest_after_actual_is_conflict():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-07-13"),
        latest_consensus=_eps(1.28, "2026-08-13"),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.surprise_pct is None
    assert gap.revision_pct is None
    assert "财报前" in gap.reason or "latest_as_of" in gap.reason


def test_L_prior_after_latest_is_conflict():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-08-12"),
        latest_consensus=_eps(1.28, "2026-08-11"),
        actual=_eps(1.30, "2026-08-13", source="company"),
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.surprise_pct is None
    assert "prior_as_of" in gap.reason or "时间顺序" in gap.reason


def test_M_different_fiscal_period_cannot_compare():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-07-13", period="FY2026Q2"),
        latest_consensus=_eps(1.28, "2026-08-11", period="FY2026Q1"),
        actual=_eps(1.30, "2026-08-12", source="company", period="FY2026Q2"),
        synthetic=True,
    )
    assert gap.status == "insufficient"
    assert gap.surprise_pct is None
    assert "fiscal period" in gap.reason

    missing = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, None),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert missing.status == "insufficient"
    illegal = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, "not-a-date"),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert illegal.status == "insufficient"


# ---------------------------------------------------------------------------
# N / O / P  (P0-3)
# ---------------------------------------------------------------------------

def test_N_duplicate_us2y_does_not_confirm():
    us2y_a = _chg("us2y", 4.00, 4.12, rule=YIELD_RULE)
    us2y_b = _chg("us2y", 4.00, 4.15, rule=YIELD_RULE)
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(us2y_a, us2y_b),
        synthetic=True,
    )
    assert confirmation.status != "confirmed"
    assert confirmation.status == "unconfirmed"
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=confirmation,
        synthetic=True,
    )
    assert impact.status != "valid"


def test_O_immaterial_cause_cannot_be_valid():
    cpi = _chg("cpi", 3.0, 3.1, rule=CPI_RULE)
    assert cpi.materiality != "material"
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(
            _chg("us2y", 4.00, 4.12, rule=YIELD_RULE),
            _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE),
            _chg("cut_odds", 42.0, 28.0, rule=ODDS_RULE),
        ),
        synthetic=True,
    )
    assert confirmation.status == "confirmed"
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target="NVDA",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmation,
        synthetic=True,
    )
    assert impact.status != "valid"
    assert "重大" in impact.reason


def test_P_wti_cannot_use_inflation_to_rates():
    oil = _chg("wti", 70.0, 77.0, rule=OIL_RULE)
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(
            _chg("us2y", 4.00, 4.12, rule=YIELD_RULE),
            _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE),
            _chg("cut_odds", 42.0, 28.0, rule=ODDS_RULE),
        ),
        synthetic=True,
    )
    impact = build_causal_impact(
        cause=oil,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(
            target="NVDA",
            target_kind="company",
            channel=CHANNEL_DURATION,
            theme="high_valuation_growth",
        ),
        market_confirmation=confirmation,
        synthetic=True,
    )
    assert impact.status != "valid"
    assert "不兼容" in impact.reason


# ---------------------------------------------------------------------------
# P0-4 counterexamples (free text / missing ID / cross-target)
# ---------------------------------------------------------------------------

def test_p0_4_thesis_requires_qualified_citations():
    free = build_thesis_snapshot(
        bull_drivers=("随便看多",),
        bear_drivers=("随便看空",),
        key_disagreement="没有证据",
        invalidation="没有失效条件依据",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert free.status == "incomplete"
    assert free.direction == "incomplete"
    assert "自由文本" in free.reason

    missing = build_thesis_snapshot(
        bull_drivers=(Driver("引用缺失", based_on=("chg|does-not-exist",)),),
        bear_drivers=(Driver("另一侧也缺", based_on=("chg|does-not-exist",)),),
        key_disagreement="缺失引用",
        invalidation="失效",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert missing.status == "incomplete"
    assert "不存在" in missing.reason

    oil, energy = _oil_producer()
    crossed = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("错把 XOM 因果用到 NVDA", based_on=(energy.id,)),),
        bear_drivers=(Driver("监管", based_on=(oil.id,)),),
        key_disagreement="标的不一致",
        invalidation="标的错配",
        changes=(oil,),
        impacts=(energy,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert crossed.status == "incomplete"
    assert "跨标的" in crossed.reason


# ---------------------------------------------------------------------------
# Q  (P0-5)
# ---------------------------------------------------------------------------

def test_Q_same_direction_but_core_evidence_changed():
    oil, energy = _oil_producer()
    previous = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(oil.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(oil,),
        impacts=(energy,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    current = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("份额扩张才是核心", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(oil.id,)),),
        key_disagreement="份额能否跟上油价",
        invalidation="油价跌破成本曲线",
        changes=(oil,),
        impacts=(energy,),
        generated_at="2026-09-11T12:00:00+00:00",
        synthetic=True,
    )
    assert previous.direction == current.direction
    report = build_what_changed(
        changes=(oil,),
        impacts=(energy,),
        previous_thesis=previous,
        current_thesis=current,
        synthetic=True,
    )
    assert report.thesis_changed is True
    assert "key_disagreement" in report.changed_fields
    assert "drivers" in report.changed_fields
    assert "direction" not in report.changed_fields


# ---------------------------------------------------------------------------
# P0-6 counterexample
# ---------------------------------------------------------------------------

def test_p0_6_what_changed_explanations_are_derived():
    oil, energy = _oil_producer()
    thesis = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(oil.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(oil,),
        impacts=(energy,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    later = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(oil.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(oil,),
        impacts=(energy,),
        generated_at="2026-09-11T12:00:00+00:00",
        synthetic=True,
    )
    assert oil.materiality == "material"
    report = build_what_changed(
        changes=(oil,),
        impacts=(energy,),
        previous_thesis=thesis,
        current_thesis=later,
        synthetic=True,
    )
    assert report.thesis_changed is False
    assert report.items
    assert all("数值变化未跨过判断阈值" not in item.why_thesis_effect for item in report.items)
    assert all("已有判断已覆盖该机制" not in item.why_thesis_effect for item in report.items)
    assert all("预期修订尚未单独推翻 Thesis" not in item.why_thesis_effect for item in report.items)
    change_item = next(item for item in report.items if item.kind == "change")
    causal_item = next(item for item in report.items if item.kind == "causal")
    assert change_item.why_it_matters == oil.summary
    assert causal_item.why_it_matters == energy.reason
    assert oil.summary in change_item.why_thesis_effect
    kinds = [item.kind for item in report.items]
    assert kinds == sorted(kinds, key=lambda kind: {"causal": 0, "expectation": 1, "change": 2, "thesis": 3}[kind])


# ---------------------------------------------------------------------------
# R / S  (P0-7)
# ---------------------------------------------------------------------------

def test_R_fundamentals_down_price_up_is_divergence():
    tension = build_price_expectation_tension(
        fundamentals_change=-10.0,
        price_change=5.0,
        synthetic=True,
    )
    assert tension.tension == "divergence"
    assert tension.divergence_kind == "fundamentals_down_price_up"
    assert tension.tension not in {"price_ahead_of_fundamentals", "aligned", "improving_faster_than_price"}
    assert "priced_in" not in tension.to_dict()


def test_S_fundamentals_up_price_down_is_divergence():
    tension = build_price_expectation_tension(
        fundamentals_change=10.0,
        price_change=-5.0,
        synthetic=True,
    )
    assert tension.tension == "divergence"
    assert tension.divergence_kind == "fundamentals_up_price_down"
    assert tension.tension not in {"price_ahead_of_fundamentals", "aligned", "improving_faster_than_price"}
    assert "priced_in" not in tension.to_dict()
