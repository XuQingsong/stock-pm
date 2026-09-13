"""Phase 3-A: graded chains and isolated degradation. Does not change kernel A–AM."""

from __future__ import annotations

from stock_pm.decision.assemble import assemble_from_bundle, assemble_from_kernel
from stock_pm.decision.preview import (
    CPI_RULE,
    VIX_RULE,
    build_preview,
    build_preview_a,
    _eps_gap,
    _macro,
    _price,
    _rate_path_expectation,
    _rates_confirmation,
)
from stock_pm.decision.thesis import Driver, build_thesis_snapshot
from stock_pm.decision.viewmodel import CHAIN_STEPS
from stock_pm.decision.grading import PRICE_MOVE_CONCLUSIONS


def _what_changed(view):
    return next(step for step in view["chain"] if step["id"] == "what_changed")


def _tension(view):
    return next(step for step in view["chain"] if step["id"] == "tension")


def _assert_no_price_move_in_can_determine(view):
    text = view["overall"].get("can_determine") or ""
    for phrase in PRICE_MOVE_CONCLUSIONS:
        assert phrase not in text, (phrase, text)


def _g(view, chain_id):
    return next(row for row in view["chains"] if row["id"] == chain_id)


def test_only_reliable_price_change_is_l1_without_direction():
    view = assemble_from_bundle(
        {
            "symbol": "NVDA",
            "watch": {"symbol": "NVDA", "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
            "bars": [
                {
                    "symbol": "NVDA",
                    "open_price": 120,
                    "high_price": 123,
                    "low_price": 119,
                    "close_price": 122,
                    "volume": 10,
                    "bar_time": "2026-09-10T20:00:00+00:00",
                    "source": "alpaca_sip",
                },
                {
                    "symbol": "NVDA",
                    "open_price": 115,
                    "high_price": 117,
                    "low_price": 114,
                    "close_price": 116,
                    "volume": 10,
                    "bar_time": "2026-09-09T20:00:00+00:00",
                    "source": "alpaca_sip",
                },
            ],
            "earnings": [],
            "macro_events": [],
            "news": [],
            "synthetic": False,
            "_skip_previous": True,
        }
    )
    assert _g(view, "price")["level"] == "L1"
    assert view["overall"]["level"] != "L0"
    assert view["overall"]["direction"] is None
    assert view["can_form_direction"] is False
    assert view["thesis"]["direction"] not in {"bullish", "bearish"}
    assert _g(view, "price")["next_required_evidence"]


def test_missing_vix_degrades_risk_not_other_complete_local_macro():
    view = build_preview("NVDA", "L2")
    assert view["synthetic"] is True
    assert _g(view, "macro_rates")["level"] == "L2"
    assert _g(view, "risk_sentiment")["level"] == "L0"
    assert _g(view, "price")["level"] == "L1"
    assert view["overall"]["level"] == "L2"
    assert view["can_form_direction"] is False
    vix_gaps = [row for row in view["gaps"] if row["code"] == "missing_vix"]
    assert vix_gaps
    assert all(row["affects_chain"] == "risk_sentiment" for row in vix_gaps)


def test_missing_prior_consensus_does_not_drop_macro_l3():
    view = build_preview_a("NVDA")
    assert _g(view, "macro_rates")["level"] == "L3"
    assert _g(view, "earnings")["level"] != "L3"
    prior = [row for row in view["gaps"] if row["code"] == "missing_prior_consensus"]
    assert prior
    assert all(row["affects_chain"] == "earnings" for row in prior)
    assert view["overall"]["level"] == "L3"
    assert view["overall"]["direction"] == "bearish"


def test_invalid_ohlc_does_not_pollute_complete_earnings_l3():
    eps = _eps_gap("NVDA")
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("EPS 相对最新共识为正", based_on=(eps.id,)),),
        bear_drivers=(Driver("估值仍不便宜", based_on=(eps.id,)),),
        key_disagreement="盈利能否消化估值",
        invalidation="盈利下修",
        expectations=(eps,),
        generated_at="2026-09-10T16:00:00+00:00",
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol="NVDA",
        changes=[],
        expectations=[eps],
        confirmation=None,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[{"code": "invalid_ohlc", "text": "价格 OHLC 未通过事实校验，不能进入 Change"}],
        facts=[],
        synthetic=True,
        as_of="2026-09-10",
    )
    assert _g(view, "price")["level"] == "L0"
    assert _g(view, "earnings")["level"] == "L3"
    assert view["overall"]["level"] == "L3"
    assert view["overall"]["direction"] == "bullish"
    assert view["can_form_direction"] is True
    ohlc = next(row for row in view["gaps"] if row["code"] == "invalid_ohlc")
    assert ohlc["affects_chain"] == "price"
    assert ohlc["affects_stage"] == "facts"


def test_unverified_news_stays_clue_and_does_not_change_price_chain():
    view = build_preview("NVDA", "B")
    news = next(row for row in view["chains"] if row["id"] == "news")
    assert news["level"] == "L1"
    assert _g(view, "price")["level"] == "L1"
    assert view["what_changed"]["thesis_changed"] is False
    assert view["can_form_direction"] is False
    assert all(row.get("direction") is None for row in view["chains"] if row["id"] == "news")


def test_opposite_l3_chains_are_overall_conflict():
    view = build_preview("NVDA", "CONFLICT")
    assert _g(view, "macro_rates")["level"] == "L3"
    assert _g(view, "earnings")["level"] == "L3"
    assert _g(view, "macro_rates")["direction"] == "bearish"
    assert _g(view, "earnings")["direction"] == "bullish"
    assert view["overall"]["status"] == "conflict"
    assert view["overall"]["conflict"] is True
    assert view["overall"]["direction"] is None
    assert view["can_form_direction"] is False


def test_multiple_l2_cannot_stack_into_l3():
    cpi = _macro("cpi", 3.0, 3.5, CPI_RULE)
    vix = _macro("vix", 16.0, 22.0, VIX_RULE)
    confirmation = _rates_confirmation(hot=True)
    expectation = _rate_path_expectation()
    price = _price("NVDA", 100.0, 104.0)
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("价格上升", based_on=(price.id,)),),
        bear_drivers=(Driver("波动上升", based_on=(vix.id,)),),
        key_disagreement="局部压力是否传到个股",
        invalidation="确认路径反转",
        changes=(cpi, vix, price),
        expectations=(expectation,),
        generated_at="2026-09-10T16:00:00+00:00",
        synthetic=True,
    )
    view = assemble_from_kernel(
        symbol="NVDA",
        changes=[cpi, vix, price],
        expectations=[expectation],
        confirmation=confirmation,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[{"code": "missing_exposure", "text": "该标的没有利率久期暴露"}],
        facts=[],
        synthetic=True,
        as_of="2026-09-10",
    )
    assert _g(view, "macro_rates")["level"] == "L2"
    assert _g(view, "risk_sentiment")["level"] == "L2"
    assert view["overall"]["level"] == "L2"
    assert view["can_form_direction"] is False
    assert view["overall"]["direction"] is None
    assert view["overall"]["conflict"] is False
    assert view["overall"]["level"] != "L3"


def test_macro_without_stock_exposure_caps_at_l2_factor():
    view = build_preview("NVDA", "L2")
    macro = _g(view, "macro_rates")
    assert macro["level"] == "L2"
    assert macro["scope"] in {"industry", "factor"}
    assert view["overall"]["level"] != "L3"


def test_every_gap_names_chain_and_stage():
    views = [
        build_preview("NVDA", "L0"),
        build_preview("NVDA", "L1"),
        build_preview("NVDA", "L2"),
        build_preview("NVDA", "L3"),
        build_preview("NVDA", "CONFLICT"),
        build_preview("NVDA", "A"),
        build_preview("NVDA", "B"),
        assemble_from_bundle(
            {
                "symbol": "NVDA",
                "watch": {"symbol": "NVDA", "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
                "bars": [],
                "earnings": [],
                "macro_events": [],
                "news": [],
                "synthetic": False,
                "_skip_previous": True,
            }
        ),
    ]
    for view in views:
        assert view["gaps"]
        for row in view["gaps"]:
            assert row.get("affects_chain"), row
            assert row.get("affects_stage"), row
            assert row.get("code") != "数据不足"


def test_every_l1_l2_chain_has_next_required_evidence():
    for key in ("L1", "L2", "A", "B", "CONFLICT"):
        view = build_preview("NVDA", key)
        for row in view["chains"]:
            if row["level"] in {"L1", "L2"}:
                assert row.get("next_required_evidence"), (key, row["id"], row["level"])


def test_stale_or_conflict_gaps_stay_on_their_own_chain():
    view = assemble_from_kernel(
        symbol="NVDA",
        changes=[],
        expectations=[],
        confirmation=None,
        impacts=[],
        thesis=build_thesis_snapshot(
            symbol="NVDA",
            bull_drivers=(Driver("观察中", based_on=()),),
            bear_drivers=(Driver("观察中", based_on=()),),
            key_disagreement="数据过期范围",
            invalidation="补齐对应链",
            generated_at="2026-09-10T16:00:00+00:00",
            synthetic=True,
        ),
        previous_thesis=None,
        data_gaps=[
            {"code": "stale_dataset", "text": "CPI 过期", "affects_chain": "macro_rates", "affects_stage": "what_changed"},
            {"code": "stale_dataset", "text": "VIX 过期", "affects_chain": "risk_sentiment", "affects_stage": "confirmation"},
            {"code": "window_mismatch", "text": "利率窗口错位", "affects_chain": "macro_rates", "affects_stage": "confirmation"},
        ],
        facts=[],
        synthetic=True,
        as_of="2026-09-10",
    )
    by_chain = {}
    for row in view["gaps"]:
        by_chain.setdefault(row["affects_chain"], []).append(row["code"])
    assert "stale_dataset" in by_chain["macro_rates"]
    assert "stale_dataset" in by_chain["risk_sentiment"]
    assert all(row.get("affects_stage") for row in view["gaps"])


def test_l0_clock_insufficient_is_unavailable():
    view = build_preview("NVDA", "L0")
    assert view["synthetic"] is True
    assert "合成演示数据" in view["preview_label"]
    assert view["overall"]["level"] == "L0"
    assert view["overall"]["status"] == "unavailable"
    assert view["overall"]["conflict"] is False
    assert view["overall"]["direction"] is None
    assert view["can_form_direction"] is False
    assert view["cannot_form_judgment"] is True
    assert view["clock_status"] == "clock_insufficient"
    clock = next(row for row in view["gaps"] if row["code"] == "clock_insufficient")
    assert clock["affects_chain"] == "page"
    assert clock["affects_stage"] == "clock"
    for row in view["chains"]:
        if row["level"] in {"L1", "L2"}:
            raise AssertionError(row)
        assert row.get("next_required_evidence") or row["level"] == "L0"


def test_graded_previews_keep_internal_chain_order():
    for key in ("L0", "L1", "L2", "L3", "CONFLICT"):
        view = build_preview("NVDA", key)
        assert view["synthetic"] is True
        assert "合成演示数据" in view["preview_label"]
        assert [step["id"] for step in view["chain"]] == [row[0] for row in CHAIN_STEPS]
        if key != "L3":
            assert view["can_form_direction"] is False or view["overall"]["status"] == "conflict"
        else:
            assert view["overall"]["level"] == "L3"
            assert view["can_form_direction"] is True


def _valid_bar(as_of: str, close: float) -> dict:
    return {
        "symbol": "NVDA",
        "open_price": close,
        "high_price": close + 2,
        "low_price": close - 1,
        "close_price": close,
        "volume": 10,
        "bar_time": as_of,
        "source": "alpaca_sip",
    }


def _invalid_ohlc_bar(as_of: str) -> dict:
    return {
        "symbol": "NVDA",
        "open_price": 120,
        "high_price": 110,
        "low_price": 119,
        "close_price": 122,
        "volume": 10,
        "bar_time": as_of,
        "source": "alpaca_sip",
    }


def _shared_non_price_bundle(bars: list[dict]) -> dict:
    return {
        "symbol": "NVDA",
        "watch": {"symbol": "NVDA", "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
        "bars": bars,
        "earnings": [
            {
                "eps_actual": 0.81,
                "eps_estimate": 0.74,
                "fiscal_period": "FY2026Q2",
                "report_date": "2026-08-28",
                "source": "fmp",
            }
        ],
        "macro_events": [
            {
                "event_type": "nfp",
                "event_time": "2026-09-05T12:30:00+00:00",
                "actual": 220,
                "prior": 140,
                "source": "FRED",
                "name": "NFP",
            }
        ],
        "news": [],
        "synthetic": False,
        "_skip_previous": True,
    }


def test_invalid_ohlc_forces_price_l0_even_when_other_bars_are_valid():
    good_bars = [
        _valid_bar("2026-09-10T20:00:00+00:00", 122),
        _valid_bar("2026-09-09T20:00:00+00:00", 116),
    ]
    mixed_bars = [_invalid_ohlc_bar("2026-09-11T20:00:00+00:00"), *good_bars]
    good = assemble_from_bundle(_shared_non_price_bundle(good_bars))
    bad = assemble_from_bundle(_shared_non_price_bundle(mixed_bars))

    assert _g(good, "price")["level"] == "L1"
    assert _g(bad, "price")["level"] == "L0"
    assert _g(bad, "price")["validated_conclusion"].startswith("价格核心事实无效")
    for chain_id in ("earnings", "macro_rates", "risk_sentiment"):
        assert _g(bad, chain_id)["level"] == _g(good, chain_id)["level"], chain_id
    _assert_no_price_move_in_can_determine(bad)
    ohlc = next(row for row in bad["gaps"] if row["code"] == "invalid_ohlc")
    assert ohlc["affects_chain"] == "price"
    assert ohlc["affects_stage"] == "facts"
    assert not any(
        item.get("metric") in {"close", "open", "high", "low", "price"}
        for item in _what_changed(bad)["items"]
    )
    tension = _tension(bad)
    assert tension["status"] == "insufficient"
    assert (tension.get("tension") or {}).get("price_change") in {None, "insufficient"}


def test_invalid_ohlc_overrides_injected_price_change_and_keeps_other_chains():
    price = _price("NVDA", 100.0, 101.0)
    eps = _eps_gap("NVDA")
    thesis = build_thesis_snapshot(
        symbol="NVDA",
        bull_drivers=(Driver("EPS 相对最新共识为正", based_on=(eps.id,)),),
        bear_drivers=(Driver("估值仍不便宜", based_on=(eps.id,)),),
        key_disagreement="盈利能否消化估值",
        invalidation="盈利下修",
        changes=(price,),
        expectations=(eps,),
        generated_at="2026-09-10T16:00:00+00:00",
        synthetic=True,
    )
    clean = assemble_from_kernel(
        symbol="NVDA",
        changes=[price],
        expectations=[eps],
        confirmation=None,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[],
        facts=[],
        synthetic=True,
        as_of="2026-09-10",
    )
    tainted = assemble_from_kernel(
        symbol="NVDA",
        changes=[price],
        expectations=[eps],
        confirmation=None,
        impacts=[],
        thesis=thesis,
        previous_thesis=None,
        data_gaps=[{"code": "invalid_ohlc", "text": "价格 OHLC 未通过事实校验，不能进入 Change"}],
        facts=[],
        synthetic=True,
        as_of="2026-09-10",
    )
    assert _g(clean, "price")["level"] == "L1"
    assert _g(tainted, "price")["level"] == "L0"
    assert _g(tainted, "earnings")["level"] == _g(clean, "earnings")["level"] == "L3"
    assert _g(tainted, "macro_rates")["level"] == _g(clean, "macro_rates")["level"]
    assert _g(tainted, "risk_sentiment")["level"] == _g(clean, "risk_sentiment")["level"]
    _assert_no_price_move_in_can_determine(tainted)
    assert not any(
        item.get("metric") in {"close", "open", "high", "low", "price"}
        for item in _what_changed(tainted)["items"]
    )


def test_nfp_without_cpi_states_nfp_fact_not_rates_chain():
    view = assemble_from_bundle(
        _shared_non_price_bundle(
            [
                _valid_bar("2026-09-10T20:00:00+00:00", 122),
                _valid_bar("2026-09-09T20:00:00+00:00", 116),
            ]
        )
    )
    macro = _g(view, "macro_rates")
    text = macro["validated_conclusion"]
    assert macro["level"] == "L1"
    assert "NFP" in text
    assert "current=220" in text
    assert "prior=140" in text
    assert "delta=80" in text
    assert "as_of=" in text
    assert "上升且达到重要性阈值" not in text
    assert "今日无重大变化" not in text
    assert "通胀/利率链已成立" in text and "不能" in text
    assert macro["source"] == "FRED"
    codes = {row["code"] for row in view["gaps"]}
    assert "missing_cpi" in codes
    assert view["overall"]["level"] == "L1"
