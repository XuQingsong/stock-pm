"""Golden tests A–J for Investment Decision Kernel v1.

All fixtures in this module are synthetic. They are not live market prints.
"""

from __future__ import annotations

import pytest

from stock_pm.decision import (
    CHANNEL_COMMODITY_REVENUE,
    CHANNEL_DURATION,
    CHANNEL_FUEL_COST,
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
    with pytest.raises(FactValidationError):
        bar = require_valid_bar(bad)
        build_change_snapshot(
            metric="close",
            previous_value=10.0,
            current_value=bar["close"],
            previous_as_of="2026-09-09",
            current_as_of="2026-09-10",
            synthetic=True,
        )


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
