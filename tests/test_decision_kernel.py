"""Golden tests A–AJ for Investment Decision Kernel v1.

All fixtures in this module are synthetic. They are not live market prints.
"""

from __future__ import annotations

import pytest

from stock_pm.decision import (
    CHANNEL_COMMODITY_REVENUE,
    CHANNEL_DURATION,
    CHANNEL_FUEL_COST,
    CausalImpact,
    Driver,
    FactRef,
    FactValidationError,
    MarketConfirmation,
    MaterialityRule,
    NO_MATERIAL_CHANGE_THESIS,
    OIL_CONSUMER_MECHANISM,
    OIL_PRODUCER_MECHANISM,
    RATES_DISCOUNT_MECHANISM,
    UNCONFIRMED,
    ValidatedBar,
    ValidatedFact,
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
from stock_pm.decision.types import SCOPE_GLOBAL, infer_scope

SYNTHETIC = True

CPI_RULE = MaterialityRule(abs_delta=0.20)
YIELD_RULE = MaterialityRule(abs_delta=0.05)  # 5bp if yield is in percent
ODDS_RULE = MaterialityRule(abs_delta=5.0)
VIX_RULE = MaterialityRule(abs_delta=1.0)
OIL_RULE = MaterialityRule(pct_delta=3.0)
PE_RULE = MaterialityRule(pct_delta=5.0)


def _ref(table: str, ref_id: str) -> FactRef:
    return FactRef(ref_table=table, ref_id=ref_id, as_of="2026-09-10", source="synthetic", synthetic=True)


def _chg(
    metric: str,
    previous,
    current,
    *,
    rule: MaterialityRule,
    window: str = "1d",
    current_as_of: str = "2026-09-10",
    previous_as_of: str = "2026-09-09",
    scope: str | None = None,
    subject: str | None = None,
    fact_refs=None,
):
    refs = fact_refs if fact_refs is not None else (_ref("synthetic_series", metric),)
    inferred = infer_scope(metric, scope)
    if inferred != SCOPE_GLOBAL:
        subj = subject or "MSFT"
        current_fact = ValidatedFact(
            metric=metric,
            value=current,
            as_of=current_as_of,
            refs=refs,
            subject=subj,
            synthetic=True,
        )
        previous_fact = None
        if previous is not None:
            previous_fact = ValidatedFact(
                metric=metric,
                value=previous,
                as_of=previous_as_of,
                refs=refs,
                subject=subj,
                synthetic=True,
            )
        return build_change_snapshot(
            metric=metric,
            current_fact=current_fact,
            previous_fact=previous_fact,
            comparison_window=window,
            materiality_rule=rule,
            synthetic=True,
        )
    return build_change_snapshot(
        metric=metric,
        previous_value=previous,
        current_value=current,
        previous_as_of=previous_as_of,
        current_as_of=current_as_of,
        comparison_window=window,
        materiality_rule=rule,
        fact_refs=refs,
        synthetic=True,
    )


def _company_chg(symbol: str, metric: str = "gross_margin", previous=40.0, current=32.0):
    refs = (_ref("synthetic_series", f"{symbol}-{metric}"),)
    return build_change_snapshot(
        metric=metric,
        current_fact=ValidatedFact(
            metric=metric,
            value=current,
            as_of="2026-09-10",
            refs=refs,
            subject=symbol,
            synthetic=True,
        ),
        previous_fact=ValidatedFact(
            metric=metric,
            value=previous,
            as_of="2026-09-09",
            refs=refs,
            subject=symbol,
            synthetic=True,
        ),
        comparison_window="1d",
        materiality_rule=MaterialityRule(abs_delta=2.0),
        synthetic=True,
    )


def _eps(
    value,
    as_of,
    *,
    period="FY2026Q2",
    source="street",
    basis="gaap",
    ref_id=None,
    subject="MSFT",
    analyst_count=None,
    fact_ref="default",
):
    ref = None
    if fact_ref is not None:
        ref = fact_ref if fact_ref != "default" else _ref("consensus", ref_id or f"{source}-{as_of}")
    return ExpectationPoint(
        value=value,
        as_of=as_of,
        source=source,
        currency="USD",
        basis=basis,
        fiscal_period=period,
        fact_ref=ref,
        analyst_count=analyst_count,
        subject=subject,
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
        prior_consensus=_eps(1.18, "2026-07-13", analyst_count=18, ref_id="prior"),
        latest_consensus=_eps(1.28, "2026-08-11", analyst_count=21, ref_id="latest"),
        actual=_eps(1.30, "2026-08-12", source="company", ref_id="print"),
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
        latest_consensus=_eps(1.28, "2026-08-11", fact_ref=None),
        actual=_eps(1.30, "2026-08-12", source="company", fact_ref=None),
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
        {
            "open": 9.8,
            "high": 10.0,
            "low": 9.7,
            "close": 10.0,
            "as_of": "2026-09-09",
            "symbol": "MSFT",
            "synthetic": True,
        }
    )
    curr = require_valid_bar(
        {
            "open": 10.0,
            "high": 10.3,
            "low": 9.9,
            "close": 10.2,
            "as_of": "2026-09-10",
            "symbol": "MSFT",
            "synthetic": True,
        }
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
        current_fact=ValidatedFact(
            metric="eps",
            value=1.30,
            as_of="2026-08-12",
            subject="MSFT",
            synthetic=True,
        ),
        previous_fact=None,
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
        latest_consensus=_eps(1.28, "2026-08-11"),
        actual=_eps(1.45, "2026-08-12", source="company", basis="non-gaap"),
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
    assert gap.code == "time_order"
    assert gap.surprise_pct is None
    assert gap.revision_pct is None


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
    assert gap.code == "time_order"
    assert gap.surprise_pct is None


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
    assert gap.code == "period_mismatch"
    assert gap.surprise_pct is None

    missing = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, None),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert missing.status == "insufficient"
    assert missing.code == "missing_as_of"
    illegal = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, "not-a-date"),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert illegal.status == "insufficient"
    assert illegal.code == "invalid_as_of"


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
    assert confirmation.code == "unconfirmed"
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
    assert impact.code == "immaterial_cause"


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
    assert impact.code == "mechanism_mismatch"


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
    assert free.code == "free_text"

    missing = build_thesis_snapshot(
        bull_drivers=(Driver("引用缺失", based_on=("chg|does-not-exist",)),),
        bear_drivers=(Driver("另一侧也缺", based_on=("chg|does-not-exist",)),),
        key_disagreement="缺失引用",
        invalidation="失效",
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert missing.status == "incomplete"
    assert missing.code == "missing_citation"

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
    assert crossed.code == "cross_symbol"


# ---------------------------------------------------------------------------
# Q  (P0-5)
# ---------------------------------------------------------------------------

def test_Q_same_direction_but_core_evidence_changed():
    oil, energy = _oil_producer()
    cost = _company_chg("XOM")
    previous = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(cost.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(cost,),
        impacts=(energy,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    current = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("份额扩张才是核心", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(cost.id,)),),
        key_disagreement="份额能否跟上油价",
        invalidation="油价跌破成本曲线",
        changes=(cost,),
        impacts=(energy,),
        generated_at="2026-09-11T12:00:00+00:00",
        synthetic=True,
    )
    assert previous.direction == current.direction
    report = build_what_changed(
        changes=(cost,),
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
    cost = _company_chg("XOM")
    thesis = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(cost.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(cost,),
        impacts=(energy,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    later = build_thesis_snapshot(
        symbol="XOM",
        bull_drivers=(Driver("油价利好上游", based_on=(energy.id,)),),
        bear_drivers=(Driver("成本与监管", based_on=(cost.id,)),),
        key_disagreement="油价能否持续",
        invalidation="油价跌破成本曲线",
        changes=(cost,),
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


# ---------------------------------------------------------------------------
# T (P0-A)
# ---------------------------------------------------------------------------

def test_T_forged_validated_bar_cannot_enter_change():
    with pytest.raises(FactValidationError):
        ValidatedBar(as_of="2026-09-10", open=10, high=8, low=11, close=10)
    with pytest.raises(FactValidationError):
        bad = ValidatedBar(as_of="2026-09-10", open=10, high=8, low=11, close=10)
        build_change_snapshot(
            metric="close",
            current_bar=bad,
            previous_bar=require_valid_bar(
                {
                    "open": 9.8,
                    "high": 10.0,
                    "low": 9.7,
                    "close": 10.0,
                    "as_of": "2026-09-09",
                    "symbol": "MSFT",
                    "synthetic": True,
                }
            ),
            synthetic=True,
        )
    with pytest.raises(FactValidationError):
        ValidatedFact(metric="cpi", value=3.1, as_of=None)
    with pytest.raises(FactValidationError):
        ValidatedBar(as_of="2026-09-10", open=10, high=float("nan"), low=9, close=10)


# ---------------------------------------------------------------------------
# U / V (P0-B)
# ---------------------------------------------------------------------------

def test_U_nvda_thesis_cannot_cite_aapl_eps_gap():
    aapl_gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-07-13", ref_id="aapl-prior", subject="AAPL"),
        latest_consensus=_eps(1.28, "2026-08-11", ref_id="aapl-latest", subject="AAPL"),
        actual=_eps(1.30, "2026-08-12", source="company", ref_id="aapl-actual", subject="AAPL"),
        synthetic=True,
    )
    assert aapl_gap.status == "ok"
    nvda_cost = _company_chg("NVDA")
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("引用 AAPL EPS", based_on=(aapl_gap.id,)),),
        bear_drivers=(Driver("NVDA 成本", based_on=(nvda_cost.id,)),),
        key_disagreement="标的错配",
        invalidation="标的错配失效",
        changes=(nvda_cost,),
        expectations=(aapl_gap,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert thesis.status == "incomplete"
    assert thesis.code == "cross_symbol"
    assert thesis.direction == "incomplete"


def test_V_macro_cpi_cannot_be_direct_nvda_driver():
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    nvda_cost = _company_chg("NVDA")
    assert cpi.scope == "global"
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("CPI 直接看多", based_on=(cpi.id,)),),
        bear_drivers=(Driver("NVDA 成本", based_on=(nvda_cost.id,)),),
        key_disagreement="宏观不能直接跳层",
        invalidation="跳层失效",
        changes=(cpi, nvda_cost),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert thesis.status == "incomplete"
    assert thesis.code == "macro_requires_causal"


# ---------------------------------------------------------------------------
# W (P0-C)
# ---------------------------------------------------------------------------

def test_W_bull_driver_cannot_cite_bearish_impact():
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
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
    assert impact.status == "valid"
    assert impact.direction == "bearish"
    nvda_cost = _company_chg("NVDA")
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("看多却引用偏空因果", based_on=(impact.id,)),),
        bear_drivers=(Driver("成本", based_on=(nvda_cost.id,)),),
        key_disagreement="极性矛盾",
        invalidation="极性失效",
        changes=(nvda_cost,),
        impacts=(impact,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert thesis.status == "incomplete"
    assert thesis.code == "polarity_mismatch"
    assert thesis.direction != "bearish"


# ---------------------------------------------------------------------------
# X (P0-D)
# ---------------------------------------------------------------------------

def test_X_two_latest_consensus_same_snapshot_conflict_keeps_both_refs():
    street = _eps(1.28, "2026-08-11", source="street", ref_id="street-latest")
    other = _eps(1.40, "2026-08-11", source="other_house", ref_id="other-latest")
    actual = _eps(1.30, "2026-08-12", source="company", ref_id="company-actual")
    prior = _eps(1.18, "2026-07-13", ref_id="street-prior")
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=prior,
        latest_consensus=street,
        conflicting_latest=other,
        actual=actual,
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.code == "source_conflict"
    assert gap.surprise_pct is None
    ref_ids = {str(item.ref_id) for item in gap.fact_refs}
    assert "street-latest" in ref_ids
    assert "other-latest" in ref_ids

    company_vs_street = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=prior,
        latest_consensus=street,
        actual=actual,
        synthetic=True,
    )
    assert company_vs_street.status == "ok"
    assert company_vs_street.code == "ok"


# ---------------------------------------------------------------------------
# Y / Z (P0-E)
# ---------------------------------------------------------------------------

def test_Y_timezone_aware_as_of_orders_in_utc():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-07-13T00:00:00+00:00", ref_id="y-prior"),
        latest_consensus=_eps(1.28, "2026-08-12T02:00:00+09:00", ref_id="y-latest"),
        actual=_eps(1.30, "2026-08-11T20:00:00+00:00", source="company", ref_id="y-actual"),
        synthetic=True,
    )
    assert gap.status == "ok"
    assert gap.code == "ok"
    assert gap.surprise_pct == pytest.approx(1.56, abs=0.01)


def test_Z_same_1d_window_months_apart_does_not_confirm():
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(
            _chg("us2y", 4.00, 4.12, rule=YIELD_RULE, current_as_of="2026-01-15", previous_as_of="2026-01-14"),
            _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE, current_as_of="2026-09-10", previous_as_of="2026-09-09"),
        ),
        synthetic=True,
    )
    assert confirmation.status != "confirmed"
    assert confirmation.code == "as_of_mismatch"
    assert confirmation.used == ()


# ---------------------------------------------------------------------------
# AA (P0-F)
# ---------------------------------------------------------------------------

def test_AA_valid_rates_impact_refs_include_cause_and_used_channels():
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    us2y = _chg("us2y", 4.00, 4.12, rule=YIELD_RULE)
    real_rate = _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE)
    cut_odds = _chg("cut_odds", 42.0, 28.0, rule=ODDS_RULE)
    vix = _chg("vix", 16.0, 18.5, rule=VIX_RULE)
    confirmation = assess_market_confirmation(
        path="rates_tightening",
        series=(us2y, real_rate, cut_odds, vix),
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
    ref_ids = {str(item.ref_id) for item in impact.fact_refs}
    assert {"cpi", "us2y", "real_rate", "cut_odds"} <= ref_ids
    assert "vix" not in ref_ids
    used_metrics = {row.metric for row in confirmation.used}
    assert used_metrics == {"us2y", "real_rate", "cut_odds"}


# ---------------------------------------------------------------------------
# AB / AC (P0-G)
# ---------------------------------------------------------------------------

def test_AB_both_negative_price_falls_faster_is_not_price_ahead_copy():
    tension = build_price_expectation_tension(
        fundamentals_change=-10.0,
        price_change=-30.0,
        synthetic=True,
    )
    assert tension.tension == "price_decline_ahead_of_fundamentals"
    assert tension.code == "price_decline_ahead"
    assert tension.tension != "price_ahead_of_fundamentals"
    assert "涨幅" not in tension.reason
    assert "improving" not in tension.tension


def test_AC_both_negative_fundamentals_worsen_faster_is_not_improving():
    tension = build_price_expectation_tension(
        fundamentals_change=-20.0,
        price_change=-5.0,
        synthetic=True,
    )
    assert tension.tension == "deteriorating_faster_than_price"
    assert tension.code == "deteriorating_faster"
    assert tension.tension != "improving_faster_than_price"
    assert "improving" not in tension.reason
    assert "涨幅" not in tension.reason


def test_missing_latest_consensus_not_ok_when_prior_exists():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        prior_consensus=_eps(1.18, "2026-07-13"),
        latest_consensus=_eps(None, "2026-08-11"),
        actual=_eps(1.30, "2026-08-12", source="company"),
        synthetic=True,
    )
    assert gap.status == "insufficient"
    assert gap.code == "missing_latest"
    assert gap.surprise_pct is None
    assert gap.revision_pct is None


def test_missing_fiscal_period_not_fully_comparable():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period=None,
        latest_consensus=_eps(1.28, "2026-08-11", period=None),
        actual=_eps(1.30, "2026-08-12", source="company", period=None),
        synthetic=True,
    )
    assert gap.status == "insufficient"
    assert gap.code == "missing_period"
    assert gap.surprise_pct is None


def _price_change(symbol: str, previous: float, current: float):
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
        refs=(_ref("bars", f"{symbol}-prev"),),
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
        refs=(_ref("bars", f"{symbol}-curr"),),
    )
    return build_change_snapshot(
        metric="close",
        current_bar=curr,
        previous_bar=prev,
        comparison_window="1d",
        materiality_rule=MaterialityRule(pct_delta=0.5),
        synthetic=True,
    )


def _forced_company_change(symbol: str, *, change_id: str, metric: str = "eps"):
    refs = (_ref("synthetic_series", f"{symbol}-{metric}"),)
    return build_change_snapshot(
        metric=metric,
        current_fact=ValidatedFact(
            metric=metric,
            value=1.20,
            as_of="2026-09-10",
            refs=refs,
            subject=symbol,
            synthetic=True,
        ),
        previous_fact=ValidatedFact(
            metric=metric,
            value=1.00,
            as_of="2026-09-09",
            refs=refs,
            subject=symbol,
            synthetic=True,
        ),
        comparison_window="1d",
        materiality_rule=MaterialityRule(abs_delta=0.05),
        change_id=change_id,
        synthetic=True,
    )


def _forged_valid_impact(target: str = "NVDA") -> CausalImpact:
    return CausalImpact(
        id="cau|forged|empty-refs",
        cause=None,
        market_confirmation=MarketConfirmation(
            path="none",
            status="insufficient",
            reason="forged",
            used=(),
        ),
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target=target, target_kind="company", channel=CHANNEL_DURATION),
        effect_target=target,
        direction="bearish",
        horizon="short",
        counter_evidence=(),
        confidence="medium",
        fact_refs=(),
        status="valid",
        reason="forged valid without refs",
        chain=("forged",),
        code="valid",
        synthetic=True,
    )


# ---------------------------------------------------------------------------
# AD (P0-1)
# ---------------------------------------------------------------------------

def test_AD_missing_provenance_cannot_form_thesis():
    with pytest.raises(FactValidationError):
        FactRef(ref_table="", ref_id="", as_of=None, source="")

    opposite = _company_chg("NVDA", "opex", previous=20.0, current=28.0)
    empty_change = build_change_snapshot(
        metric="gross_margin",
        current_fact=ValidatedFact(
            metric="gross_margin",
            value=32.0,
            as_of="2026-09-10",
            subject="NVDA",
            refs=(),
            synthetic=True,
        ),
        previous_fact=ValidatedFact(
            metric="gross_margin",
            value=40.0,
            as_of="2026-09-09",
            subject="NVDA",
            refs=(),
            synthetic=True,
        ),
        comparison_window="1d",
        materiality_rule=MaterialityRule(abs_delta=2.0),
        synthetic=True,
    )
    assert empty_change.materiality == "material"
    assert empty_change.fact_refs == ()
    from_change = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("无来源变化", based_on=(empty_change.id,)),),
        bear_drivers=(Driver("有来源成本", based_on=(opposite.id,)),),
        key_disagreement="来源",
        invalidation="来源失效",
        changes=(empty_change, opposite),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert from_change.status == "incomplete"
    assert from_change.code == "missing_provenance"

    empty_gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, "2026-08-11", subject="NVDA", fact_ref=None),
        actual=_eps(1.30, "2026-08-12", source="company", subject="NVDA", fact_ref=None),
        synthetic=True,
    )
    assert empty_gap.status == "ok"
    assert empty_gap.fact_refs == ()
    from_gap = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("无来源预期", based_on=(empty_gap.id,)),),
        bear_drivers=(Driver("有来源成本", based_on=(opposite.id,)),),
        key_disagreement="来源",
        invalidation="来源失效",
        changes=(opposite,),
        expectations=(empty_gap,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert from_gap.status == "incomplete"
    assert from_gap.code == "missing_provenance"

    forged = _forged_valid_impact("NVDA")
    from_impact = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("伪造因果", based_on=(forged.id,)),),
        bear_drivers=(Driver("有来源成本", based_on=(opposite.id,)),),
        key_disagreement="来源",
        invalidation="来源失效",
        changes=(opposite,),
        impacts=(forged,),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert from_impact.status == "incomplete"
    assert from_impact.code == "missing_provenance"


# ---------------------------------------------------------------------------
# AE / AF (P0-2)
# ---------------------------------------------------------------------------

def test_AE_same_period_eps_and_price_ids_differ_by_subject():
    aapl_eps = _company_chg("AAPL", "eps", previous=1.00, current=1.20)
    nvda_eps = _company_chg("NVDA", "eps", previous=1.00, current=1.20)
    assert aapl_eps.id != nvda_eps.id
    assert "AAPL" in aapl_eps.id
    assert "NVDA" in nvda_eps.id
    aapl_px = _price_change("AAPL", 100.0, 102.0)
    nvda_px = _price_change("NVDA", 100.0, 102.0)
    assert aapl_px.id != nvda_px.id
    assert "AAPL" in aapl_px.id
    assert "NVDA" in nvda_px.id


def test_AF_duplicate_evidence_id_makes_thesis_incomplete():
    aapl = _forced_company_change("AAPL", change_id="dup")
    nvda = _forced_company_change("NVDA", change_id="dup")
    assert aapl.id == nvda.id
    assert aapl != nvda
    thesis = build_thesis_snapshot(
        symbol="AAPL",
        bull_drivers=(Driver("AAPL", based_on=(aapl.id,)),),
        bear_drivers=(Driver("NVDA 被写成同一 ID", based_on=(nvda.id,)),),
        key_disagreement="ID 碰撞",
        invalidation="ID 碰撞失效",
        changes=(aapl, nvda),
        generated_at="2026-09-10T12:00:00+00:00",
        synthetic=True,
    )
    assert thesis.status == "incomplete"
    assert thesis.code == "duplicate_evidence_id"


# ---------------------------------------------------------------------------
# AG / AH (P0-3)
# ---------------------------------------------------------------------------

def test_AG_cannot_relabel_aapl_evidence_as_nvda():
    aapl_curr = ValidatedFact(
        metric="eps",
        value=1.30,
        as_of="2026-09-10",
        subject="AAPL",
        refs=(_ref("synthetic_series", "aapl-eps-curr"),),
        synthetic=True,
    )
    aapl_prev = ValidatedFact(
        metric="eps",
        value=1.10,
        as_of="2026-09-09",
        subject="AAPL",
        refs=(_ref("synthetic_series", "aapl-eps-prev"),),
        synthetic=True,
    )
    with pytest.raises(FactValidationError):
        build_change_snapshot(
            metric="eps",
            current_fact=aapl_curr,
            previous_fact=aapl_prev,
            comparison_window="1d",
            materiality_rule=MaterialityRule(abs_delta=0.05),
            subject="NVDA",
            synthetic=True,
        )
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, "2026-08-11", subject="AAPL"),
        actual=_eps(1.30, "2026-08-12", source="company", subject="AAPL"),
        subject="NVDA",
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.code == "identity_override"


def test_AH_mixed_input_subjects_are_conflict():
    gap = build_expectation_gap(
        metric="eps",
        fiscal_period="FY2026Q2",
        latest_consensus=_eps(1.28, "2026-08-11", subject="AAPL"),
        actual=_eps(1.30, "2026-08-12", source="company", subject="NVDA"),
        synthetic=True,
    )
    assert gap.status == "conflict"
    assert gap.code == "subject_mismatch"
    with pytest.raises(FactValidationError):
        build_change_snapshot(
            metric="eps",
            current_fact=ValidatedFact(
                metric="eps",
                value=1.30,
                as_of="2026-09-10",
                subject="AAPL",
                synthetic=True,
            ),
            previous_fact=ValidatedFact(
                metric="eps",
                value=1.10,
                as_of="2026-09-09",
                subject="NVDA",
                synthetic=True,
            ),
            synthetic=True,
        )


# ---------------------------------------------------------------------------
# AI / AJ (P0-4)
# ---------------------------------------------------------------------------

def test_AI_forged_confirmed_empty_used_is_not_valid():
    with pytest.raises(FactValidationError):
        MarketConfirmation(
            path="rates_tightening",
            status="confirmed",
            reason="forged",
            used=(),
        )
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    empty = assess_market_confirmation(path="rates_tightening", series=(), synthetic=True)
    assert empty.status != "confirmed"
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=empty,
        synthetic=True,
    )
    assert impact.status != "valid"
    unconfirmed = MarketConfirmation(
        path="rates_tightening",
        status="unconfirmed",
        reason=UNCONFIRMED,
        used=(),
    )
    still_blocked = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=unconfirmed,
        synthetic=True,
    )
    assert still_blocked.status != "valid"


def test_AJ_duplicate_missing_refs_or_wrong_direction_used_cannot_confirm():
    us2y_a = _chg("us2y", 4.00, 4.12, rule=YIELD_RULE)
    us2y_b = _chg("us2y", 4.00, 4.15, rule=YIELD_RULE)
    real_rate = _chg("real_rate", 1.50, 1.62, rule=YIELD_RULE)
    with pytest.raises(FactValidationError):
        MarketConfirmation(
            path="rates_tightening",
            status="confirmed",
            reason="duplicate channel",
            used=(us2y_a, us2y_b),
        )
    no_refs = _chg("us2y", 4.00, 4.12, rule=YIELD_RULE, fact_refs=())
    with pytest.raises(FactValidationError):
        MarketConfirmation(
            path="rates_tightening",
            status="confirmed",
            reason="missing refs",
            used=(no_refs, real_rate),
        )
    us2y_down = _chg("us2y", 4.12, 4.00, rule=YIELD_RULE)
    with pytest.raises(FactValidationError):
        MarketConfirmation(
            path="rates_tightening",
            status="confirmed",
            reason="wrong direction",
            used=(us2y_down, real_rate),
        )
    assert assess_market_confirmation(
        path="rates_tightening",
        series=(no_refs, real_rate),
        synthetic=True,
    ).status != "confirmed"
    assert assess_market_confirmation(
        path="rates_tightening",
        series=(us2y_down, real_rate),
        synthetic=True,
    ).status != "confirmed"
    cpi = _chg("cpi", 3.0, 3.5, rule=CPI_RULE)
    impact = build_causal_impact(
        cause=cpi,
        mechanism=RATES_DISCOUNT_MECHANISM,
        exposure=Exposure(target="NVDA", target_kind="company", channel=CHANNEL_DURATION),
        market_confirmation=assess_market_confirmation(
            path="rates_tightening",
            series=(no_refs, real_rate),
            synthetic=True,
        ),
        synthetic=True,
    )
    assert impact.status != "valid"
