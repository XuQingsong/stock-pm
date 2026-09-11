"""Adapter, view-model, and A/B/C preview tests for the stock decision chain."""

from __future__ import annotations

from stock_pm.decision.assemble import assemble_from_bundle
from stock_pm.decision.preview import build_preview, preview_allowed
from stock_pm.decision.viewmodel import CHAIN_STEPS
from stock_pm.config import Settings


def _chain(view, key):
    return next(step for step in view["chain"] if step["id"] == key)


def test_preview_A_confirmed_macro_chain_is_traceable():
    view = build_preview("NVDA", "A")
    assert view["synthetic"] is True
    assert view["preview"] == "A"
    assert "合成演示数据" in view["preview_label"]
    assert [step["id"] for step in view["chain"]] == [row[0] for row in CHAIN_STEPS]
    confirm = _chain(view, "confirmation")
    trans = _chain(view, "transmission")
    impact = trans["items"][0]
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
    what = _chain(view, "what_changed")
    assert what["items"]
    assert all("ref" in item or item.get("refs") for item in what["items"])


def test_preview_B_unverified_does_not_change_thesis():
    view = build_preview("NVDA", "B")
    assert view["synthetic"] is True
    trans = _chain(view, "transmission")
    assert trans["items"][0]["status"] == "unverified"
    assert trans["items"][0]["direction"] is None
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
    confirm = _chain(view, "confirmation")
    assert confirm["status"] != "confirmed"


def test_live_bundle_without_yields_does_not_jump_to_stock():
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
    trans = _chain(view, "transmission")
    assert all(item["status"] != "valid" for item in trans["items"])
    expect = _chain(view, "expectation")
    assert expect["status"] != "ok"
    what = _chain(view, "what_changed")
    assert what["items"]
    price = next(item for item in what["items"] if item["metric"] == "close")
    assert price["ref"]["source"] == "alpaca_sip"
    assert price["ref"]["as_of"]
    nfp = next(item for item in what["items"] if item["metric"] == "nfp")
    assert nfp["scope"] == "global"


def test_preview_disabled_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert preview_allowed(Settings()) is False
