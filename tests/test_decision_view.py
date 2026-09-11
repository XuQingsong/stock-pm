"""Adapter, view-model, and A/B/C preview tests for the stock decision chain."""

from __future__ import annotations

from datetime import date

from stock_pm.decision.assemble import assemble_from_bundle
from stock_pm.decision.causal import (
    MECHANISMS_REQUIRING_EXPECTATION,
    MECHANISMS_WITHOUT_EXPECTATION,
    OIL_CONSUMER_MECHANISM,
    OIL_PRODUCER_MECHANISM,
    RATES_DISCOUNT_MECHANISM,
)
from stock_pm.decision.clock import dataset_as_of, macro_window, partition_macros
from stock_pm.decision.preview import build_preview, build_preview_a, preview_allowed
from stock_pm.decision.viewmodel import CHAIN_STEPS
from stock_pm.config import Settings


def _chain(view, key):
    return next(step for step in view["chain"] if step["id"] == key)


def _causal(view):
    return _chain(view, "causal_impact")


def test_rates_mechanism_requires_expectation_oil_does_not():
    assert RATES_DISCOUNT_MECHANISM in MECHANISMS_REQUIRING_EXPECTATION
    assert OIL_PRODUCER_MECHANISM in MECHANISMS_WITHOUT_EXPECTATION
    assert OIL_CONSUMER_MECHANISM in MECHANISMS_WITHOUT_EXPECTATION
    assert OIL_PRODUCER_MECHANISM not in MECHANISMS_REQUIRING_EXPECTATION
    assert [row[0] for row in CHAIN_STEPS] == [
        "what_changed",
        "expectation",
        "tension",
        "causal_impact",
        "thesis_impact",
    ]


def test_preview_A_confirmed_macro_chain_is_traceable():
    view = build_preview("NVDA", "A")
    assert view["synthetic"] is True
    assert view["preview"] == "A"
    assert "合成演示数据" in view["preview_label"]
    assert [step["id"] for step in view["chain"]] == [row[0] for row in CHAIN_STEPS]
    assert "tension" in [step["id"] for step in view["chain"]]
    causal = _causal(view)
    confirm = causal["confirmation"]
    impact = causal["items"][0]
    assert confirm["status"] == "confirmed"
    assert impact["status"] == "valid"
    assert impact["direction"] == "bearish"
    assert impact["mechanism"] == "inflation_to_rates_to_discount"
    assert impact["exposure"]["channel"] == "high_valuation_duration"
    assert impact["current"] == 3.5
    assert impact["previous"] == 3.0
    assert impact["window"]
    assert impact["refs"]
    assert all(ref.get("source") and ref.get("as_of") and ref.get("ref_table") for ref in impact["refs"])
    thesis_step = _chain(view, "thesis_impact")
    assert "drivers" in thesis_step["changed_fields"] or "key_disagreement" in thesis_step["changed_fields"]
    assert thesis_step["thesis_changed"] is True
    assert view["thesis"]["direction"] == "bearish"
    assert view["thesis"]["evidence_quality"] == "complete"
    assert view["cannot_form_judgment"] is False
    what = _chain(view, "what_changed")
    assert what["items"]
    metrics = {item["metric"] for item in what["items"]}
    assert "cpi" in metrics
    assert "close" in metrics
    assert "us2y" not in metrics
    assert all("ref" in item or item.get("refs") for item in what["items"])


def test_preview_A_expectation_and_tension_before_complete_bearish():
    view = build_preview_a("NVDA")
    expect = _chain(view, "expectation")
    assert expect["status"] == "ok"
    assert expect["items"]
    item = expect["items"][0]
    assert item["metric"] == "cut_odds"
    assert item["current"] == 28.0
    assert item["previous"] == 42.0
    assert item["prior"] == 42.0
    assert item["delta"] == -14.0
    assert item["ref"]["as_of"]
    assert item["ref"]["source"]
    assert item["as_of"]
    assert item["previous_as_of"]
    tension = _chain(view, "tension")
    assert tension["status"] != "insufficient"
    assert tension["tension"]["price_change"] is not None
    assert tension["tension"]["fundamentals_change"] is not None
    assert tension["status"] in {
        "divergence",
        "aligned",
        "price_ahead_of_fundamentals",
        "price_decline_ahead_of_fundamentals",
        "improving_faster_than_price",
        "deteriorating_faster_than_price",
    }
    assert view["evidence_quality"] == "complete"
    assert view["thesis"]["direction"] == "bearish"
    assert view["cannot_form_judgment"] is False


def test_removing_expectation_blocks_complete_and_thesis_direction():
    view = build_preview_a("NVDA", include_expectation=False)
    expect = _chain(view, "expectation")
    assert expect["status"] != "ok"
    assert expect["items"] == []
    assert view["cannot_form_judgment"] is True
    assert "目前不能形成判断" in (view["cannot_form_judgment_reason"] or "")
    assert view["evidence_quality"] != "complete"
    assert view["thesis"]["direction"] not in {"bearish", "bullish"}
    assert view["thesis"]["based_on_causal_impact_ids"] == []
    causal = _causal(view)
    assert causal["status"] == "watch"
    assert causal["confirmation"]["status"] == "confirmed"
    assert all(item.get("status") != "valid" or item.get("direction") is None for item in causal["items"])
    thesis_step = _chain(view, "thesis_impact")
    assert thesis_step["status"] != "ok"


def test_removing_price_makes_tension_insufficient_and_not_complete():
    view = build_preview_a("NVDA", include_price=False)
    tension = _chain(view, "tension")
    assert tension["status"] == "insufficient"
    assert view["cannot_form_judgment"] is True
    assert view["evidence_quality"] != "complete"
    assert view["thesis"]["direction"] not in {"bearish", "bullish"}
    assert view["rates_chain_blocked"] is True


def test_tension_aligned_vs_divergence_changes_thesis_impact():
    diverged = build_preview_a("NVDA", previous_close=100.0, current_close=104.0)
    reflected = build_preview_a("NVDA", previous_close=100.0, current_close=67.0)
    div_t = _chain(diverged, "tension")
    ref_t = _chain(reflected, "tension")
    assert div_t["status"] != ref_t["status"]
    assert div_t["status"] == "divergence"
    assert ref_t["status"] == "aligned"
    div_thesis = _chain(diverged, "thesis_impact")
    ref_thesis = _chain(reflected, "thesis_impact")
    assert div_thesis["tension_status"] != ref_thesis["tension_status"]
    assert div_thesis["items"] != ref_thesis["items"] or div_thesis["derived_reason"] != ref_thesis["derived_reason"]
    assert diverged["thesis"]["direction"] == "bearish"
    assert reflected["cannot_form_judgment"] is False or reflected["thesis"]["direction"] != diverged["thesis"]["direction"] or div_thesis != ref_thesis


def test_preview_B_unverified_does_not_change_thesis():
    view = build_preview("NVDA", "B")
    assert view["synthetic"] is True
    causal = _causal(view)
    assert causal["items"][0]["status"] == "unverified"
    assert causal["items"][0]["direction"] is None
    thesis_step = _chain(view, "thesis_impact")
    assert thesis_step["thesis_changed"] is False
    assert view["thesis"]["status"] != "ok" or view["what_changed"]["thesis_changed"] is False
    assert any("线索" in row["text"] or row["code"] == "unverified_news" for row in view["gaps"])
    assert view["clues"]
    assert view["clues"][0]["status"] == "unverified"


def test_preview_C_no_material_change_is_explicit():
    view = build_preview("AAPL", "C")
    assert view["no_material_change"] is True
    assert "无重大变化" in view["what_changed"]["summary"]
    what = _chain(view, "what_changed")
    assert what["status"] == "immaterial"
    assert view["what_changed"]["thesis_changed"] is False
    confirm = _causal(view)["confirmation"]
    assert confirm["status"] != "confirmed"
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
            "cboe": None,
            "synthetic": False,
            "_skip_previous": True,
        }
    )
    assert view["synthetic"] is False
    codes = {row["code"] for row in view["gaps"]}
    assert "missing_vix" in codes
    assert "missing_rates_confirmation" in codes
    assert "missing_prior_consensus" in codes
    assert "missing_cpi" in codes
    causal = _causal(view)
    assert causal["items"] == []
    assert causal["status"] == "insufficient"
    assert "missing_mechanism" in codes
    expect = _chain(view, "expectation")
    assert expect["status"] != "ok"
    what = _chain(view, "what_changed")
    assert what["items"]
    price = next(item for item in what["items"] if item["metric"] == "close")
    assert price["ref"]["source"] == "alpaca_sip"
    assert price["ref"]["as_of"]
    nfp = next(item for item in what["items"] if item["metric"] == "nfp")
    assert nfp["scope"] == "global"
    assert view["cannot_form_judgment"] is True
    assert "目前不能形成判断" in (view["cannot_form_judgment_reason"] or "")
    tension = _chain(view, "tension")
    assert tension["status"] == "insufficient"
    assert _causal(view)["confirmation"]["status"] != "confirmed"


def test_live_missing_expectation_tension_cannot_form_judgment():
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
    assert view["synthetic"] is False
    assert [step["id"] for step in view["chain"]] == [row[0] for row in CHAIN_STEPS]
    expect = _chain(view, "expectation")
    tension = _chain(view, "tension")
    assert expect["status"] != "ok"
    assert tension["status"] == "insufficient"
    assert view["cannot_form_judgment"] is True
    assert "目前不能形成判断" in (view["cannot_form_judgment_reason"] or "")
    assert view["evidence_quality"] != "complete"
    assert view["thesis"]["direction"] not in {"bearish", "bullish"}
    confirm = _causal(view)["confirmation"]
    assert confirm["status"] != "ok"
    # Confirmation must not patch a missing Expectation / Tension into a complete judgment.
    assert view["thesis"]["evidence_quality"] != "complete" or view["cannot_form_judgment"] is True


def test_invalid_latest_ohlc_is_gap_not_a_price_change():
    view = assemble_from_bundle(
        {
            "symbol": "NVDA",
            "watch": {"symbol": "NVDA", "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
            "bars": [
                {
                    "symbol": "NVDA",
                    "open_price": 116,
                    "high_price": 118,
                    "low_price": 115,
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
    codes = {row["code"] for row in view["gaps"]}
    assert "invalid_ohlc" in codes
    what = _chain(view, "what_changed")
    assert all(item.get("metric") != "close" for item in what["items"])


def test_preview_requires_explicit_dual_opt_in(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENABLE_DECISION_PREVIEW", raising=False)
    assert preview_allowed() is False
    assert preview_allowed(Settings()) is False

    denied = [
        ("", "true"),
        ("   ", "true"),
        ("staging", "true"),
        ("production", "true"),
        ("prod", "true"),
        (" PRODUCTION ", "true"),
        ("Prod", "true"),
        ("production", "false"),
        ("development", ""),
        ("development", "false"),
        ("development", "0"),
        ("test", "no"),
        (None, "true"),
        ("development", None),
    ]
    for env, flag in denied:
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ENABLE_DECISION_PREVIEW", raising=False)
        if env is not None:
            monkeypatch.setenv("APP_ENV", env)
        if flag is not None:
            monkeypatch.setenv("ENABLE_DECISION_PREVIEW", flag)
        assert preview_allowed() is False, (env, flag)
        assert preview_allowed(Settings()) is False, (env, flag)

    allowed = [
        ("development", "true"),
        (" DEVELOPMENT ", "TRUE"),
        ("test", "1"),
        ("local", "yes"),
        ("local", "on"),
    ]
    for env, flag in allowed:
        monkeypatch.setenv("APP_ENV", env)
        monkeypatch.setenv("ENABLE_DECISION_PREVIEW", flag)
        assert preview_allowed() is True, (env, flag)
        assert preview_allowed(Settings()) is True, (env, flag)


def test_old_macros_stay_in_window_when_wall_clock_is_later():
    today = date(2028, 1, 1)
    bars = [{"bar_time": "2026-09-10T20:00:00+00:00"}]
    macros = [{"event_type": "cpi", "event_time": "2026-09-05T12:30:00+00:00", "actual": 3.5}]
    clock = dataset_as_of(bars=bars, macros=macros)
    assert clock == date(2026, 9, 10)
    start, end = macro_window(clock)
    inside, stale, mismatch = partition_macros(macros, start=start, end=end)
    assert len(inside) == 1
    assert stale == []
    assert mismatch == []
    wall_start, wall_end = macro_window(today)
    _inside, wall_stale, _mismatch = partition_macros(macros, start=wall_start, end=wall_end)
    assert wall_stale and not _inside


def test_future_fomc_does_not_advance_dataset_clock():
    clock = dataset_as_of(
        bars=[{"bar_time": "2026-09-10T20:00:00+00:00", "source_as_of": "2026-09-10T20:00:00+00:00"}],
        macros=[{"event_type": "fomc", "event_time": "2026-12-15T18:00:00+00:00", "name": "FOMC"}],
    )
    assert clock == date(2026, 9, 10)


def test_future_earnings_release_does_not_advance_dataset_clock():
    clock = dataset_as_of(
        bars=[{"bar_time": "2026-09-10T20:00:00+00:00"}],
        earnings=[{
            "report_date": "2026-11-20",
            "release_date": "2026-11-20",
            "fiscal_period": "FY2027Q1",
            "period_end": "2026-10-31",
            "eps_actual": None,
            "eps_estimate": 0.9,
        }],
    )
    assert clock == date(2026, 9, 10)


def test_only_scheduled_macro_is_not_observed_not_confirmed():
    view = assemble_from_bundle(
        _coverage_bundle(
            bars=[
                {
                    "symbol": "NVDA",
                    "open_price": 115,
                    "high_price": 117,
                    "low_price": 114,
                    "close_price": 116,
                    "volume": 10,
                    "bar_time": "2026-09-10T20:00:00+00:00",
                    "source": "alpaca_sip",
                },
                {
                    "symbol": "NVDA",
                    "open_price": 114,
                    "high_price": 116,
                    "low_price": 113,
                    "close_price": 115,
                    "volume": 10,
                    "bar_time": "2026-09-09T20:00:00+00:00",
                    "source": "alpaca_sip",
                },
            ],
            macro_events=[{
                "event_type": "fomc",
                "event_time": "2026-12-15T18:00:00+00:00",
                "name": "FOMC",
                "actual": None,
                "prior": None,
                "source": "calendar",
            }],
        )
    )
    codes = {row["code"] for row in view["gaps"]}
    assert "not_observed" in codes
    causal = _causal(view)
    assert all(item.get("status") != "valid" for item in causal["items"])
    confirm = causal["confirmation"]
    assert confirm["status"] != "confirmed"
    assert view["as_of"].startswith("2026-09-10")
    assert all(
        item.get("metric") != "fomc"
        for item in _chain(view, "what_changed")["items"]
    )


def test_no_observation_timestamp_is_clock_insufficient():
    view = assemble_from_bundle(
        _coverage_bundle(
            bars=[],
            earnings=[{"report_date": "2026-11-20", "fiscal_period": "FY2027Q1", "eps_actual": None}],
            macro_events=[{
                "event_type": "fomc",
                "event_time": "2026-12-15T18:00:00+00:00",
                "actual": None,
                "source": "calendar",
            }],
        )
    )
    codes = {row["code"] for row in view["gaps"]}
    assert "clock_insufficient" in codes
    assert view["clock_status"] == "clock_insufficient"
    assert view["as_of"] is None
    assert view["cannot_form_judgment"] is True
    assert view["cannot_form_judgment_reason"]
    causal = _causal(view)
    assert all(item.get("status") != "valid" for item in causal["items"])


def _coverage_bundle(**extra):
    payload = {
        "symbol": "NVDA",
        "watch": {"symbol": "NVDA", "themes": ["high_valuation_growth"], "rate_sensitivity": "high"},
        "bars": [],
        "earnings": [],
        "macro_events": [],
        "news": [],
        "synthetic": False,
        "_skip_previous": True,
    }
    payload.update(extra)
    return payload


def _price_bars():
    return [
        {
            "symbol": "NVDA",
            "open_price": 115,
            "high_price": 117,
            "low_price": 114,
            "close_price": 116,
            "volume": 10,
            "bar_time": "2026-09-10T20:00:00+00:00",
            "source": "alpaca_sip",
        },
        {
            "symbol": "NVDA",
            "open_price": 114,
            "high_price": 116,
            "low_price": 113,
            "close_price": 115,
            "volume": 10,
            "bar_time": "2026-09-09T20:00:00+00:00",
            "source": "alpaca_sip",
        },
    ]


def test_stale_cpi_is_not_reported_as_missing():
    view = assemble_from_bundle(
        _coverage_bundle(
            bars=_price_bars(),
            macro_events=[
                {
                    "event_type": "cpi",
                    "event_time": "2025-01-15T12:30:00+00:00",
                    "actual": 3.5,
                    "prior": 3.0,
                    "source": "FRED",
                    "name": "CPI",
                }
            ],
        )
    )
    codes = {row["code"] for row in view["gaps"]}
    assert "stale_dataset" in codes
    assert "missing_cpi" not in codes
    assert any("不是数据缺失" in row["text"] for row in view["gaps"] if row["code"] == "stale_dataset")


def test_window_mismatch_cpi_is_not_reported_as_missing():
    view = assemble_from_bundle(
        _coverage_bundle(
            bars=_price_bars(),
            macro_events=[
                {
                    "event_type": "cpi",
                    "event_time": "2027-03-01T12:30:00+00:00",
                    "actual": 3.5,
                    "prior": 3.0,
                    "source": "FRED",
                    "name": "CPI",
                }
            ],
        )
    )
    codes = {row["code"] for row in view["gaps"]}
    assert "not_observed" in codes
    assert "missing_cpi" not in codes
    assert view["as_of"].startswith("2026-09-10")
