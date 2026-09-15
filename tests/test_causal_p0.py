from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.config import DEFAULT_WATCHLIST
from stock_pm.decision.assemble import assemble_from_bundle
from stock_pm.decision.inject import apply_inject, inject_allowed, parse_inject_tokens
from stock_pm.decision.path import build_rates_path, has_duration_exposure
from stock_pm.nfp import nfp_from_payems
from stock_pm.prediction import withhold_unsourced_prediction
from stock_pm.series import parse_fred_observations

from test_api import FakeDatabase, _empty_live_overlay


def _bar(symbol: str, close: float, stamp: str) -> dict:
    return {
        "symbol": symbol,
        "open_price": close - 1,
        "high_price": close + 1,
        "low_price": close - 2,
        "close_price": close,
        "volume": 10,
        "bar_time": stamp,
        "source": "alpaca_sip",
        "http_source": "https://data.alpaca.markets/v2/stocks/bars",
    }


def _earn(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "eps_actual": 2.22,
        "eps_estimate": 2.09,
        "fiscal_period": "FY2026Q2",
        "report_date": "2026-08-28",
        "source": "fmp",
        "http_source": "https://financialmodelingprep.com/api/v3/historical/earning_calendar",
    }


def _macro(event_type: str, actual: float, prior: float, stamp: str, **extra) -> dict:
    row = {
        "event_type": event_type,
        "event_time": stamp,
        "actual": actual,
        "prior": prior,
        "prior_as_of": "2026-08-01T00:00:00+00:00",
        "source": extra.pop("source", "FRED"),
        "name": extra.pop("name", event_type.upper()),
        "unit": extra.get("unit"),
        "series": extra.get("series"),
        "series_or_symbol": extra.get("series"),
        "http_source": extra.pop("http_source", "https://fred.stlouisfed.org/graph/fredgraph.csv"),
        "status": "ok",
        "origin": "primary",
        "formula": extra.pop("formula", None),
        "comparison": extra.pop("comparison", "same_series_same_unit"),
    }
    row.update(extra)
    return row


def _watch(symbol: str) -> dict:
    seed = DEFAULT_WATCHLIST[symbol]
    return {
        "symbol": symbol,
        "themes": list(seed.themes),
        "rate_sensitivity": seed.rate_sensitivity,
    }


def _bundle(symbol: str, *, nfp_prior: float = 212.0, extras: list[dict] | None = None) -> dict:
    macros = [
        _macro("cpi", 334.131, 333.9, "2026-08-01T00:00:00+00:00", series="CPIAUCSL", unit="index"),
        _macro("us2y", 4.56, 4.50, "2026-09-11T00:00:00+00:00", series="DGS2", unit="percent"),
        _macro("vix", 17.84, 16.2, "2026-09-11T00:00:00+00:00", series="VIXCLS", unit="index"),
        _macro(
            "nfp",
            162.0,
            nfp_prior,
            "2026-09-04T00:00:00+00:00",
            series="PAYEMS",
            unit="thousands",
            formula="ΔPAYEMS[t] = PAYEMS[t] − PAYEMS[t−1]（千人）",
            comparison="same_definition_monthly_diff",
        ),
        _macro("gold", 2400.0, 2380.0, "2026-09-11T00:00:00+00:00", series="XAUUSD", unit="USD"),
    ]
    if extras:
        macros.extend(extras)
    return {
        "symbol": symbol,
        "watch": _watch(symbol),
        "bars": [
            _bar(symbol, 218.29, "2026-09-11T20:00:00+00:00"),
            _bar(symbol, 216.0, "2026-09-10T20:00:00+00:00"),
        ],
        "earnings": [_earn(symbol)],
        "macro_events": macros,
        "news": [],
        "synthetic": False,
        "_skip_previous": True,
    }


def test_nfp_prior_is_previous_month_diff_not_payems_stock():
    fixture = parse_fred_observations(
        json.loads(Path("tests/fixtures/fred_payems.json").read_text())
    )
    derived = nfp_from_payems(fixture)
    assert derived["value"] == 220.0
    assert derived["prior_change"] == 212.0
    assert derived["prior_level"] == 159612.0
    assert derived["prior_change"] != derived["prior_level"]


def test_nfp_rejects_stock_as_prior():
    view = assemble_from_bundle(_bundle("NVDA", nfp_prior=158913))
    codes = {row["code"] for row in view["gaps"]}
    assert "nfp_unit_mismatch" in codes
    nfp_change = [
        row for row in view["chain"][0]["items"] if row.get("metric") == "nfp"
    ]
    assert nfp_change == []
    nfp_fact = next(row for row in view["market_background"] if row["metric"] == "nfp")
    assert nfp_fact["previous"] is None
    assert nfp_fact["value"] == 162.0


def test_nfp_same_definition_fields_on_change():
    view = assemble_from_bundle(_bundle("NVDA", nfp_prior=140.0))
    nfp = next(row for row in view["market_background"] if row["metric"] == "nfp")
    assert nfp["value"] == 162.0
    assert nfp["previous"] == 140.0
    assert nfp["series"] == "PAYEMS"
    assert nfp["unit"] == "thousands"
    assert nfp["period"]
    assert nfp["formula"]
    assert abs(nfp["previous"]) < 10000


def test_ok_macros_are_not_missing_on_decision():
    view = assemble_from_bundle(_bundle("NVDA"))
    codes = {row["code"] for row in view["gaps"]}
    assert "missing_cpi" not in codes
    assert "missing_rates_confirmation" not in codes
    assert "missing_vix" not in codes
    metrics = {row["metric"] for row in view["facts"] + view["market_background"]}
    assert {"cpi", "us2y", "vix", "nfp", "close"} <= metrics


def test_us2y_alone_is_enough_rates_confirmation():
    bundle = _bundle("NVDA")
    bundle["macro_events"] = [
        row for row in bundle["macro_events"] if row["event_type"] in {"cpi", "us2y"}
    ]
    view = assemble_from_bundle(bundle)
    codes = {row["code"] for row in view["gaps"]}
    assert "missing_rates_confirmation" not in codes
    assert "missing_vix" in codes


def test_nvda_rates_path_visible_aapl_nok_not_copied():
    nvda = assemble_from_bundle(_bundle("NVDA"))
    aapl = assemble_from_bundle(_bundle("AAPL"))
    nok = assemble_from_bundle(_bundle("NOK"))
    assert nvda["rates_path"]["status"] == "visible"
    assert nvda["rates_path"]["direction"] in {"pressure", "watch"}
    assert nvda["rates_path"]["horizon"] == "short"
    assert [node["id"] for node in nvda["rates_path"]["nodes"]] == [
        "cpi",
        "us2y",
        "discount",
        "industry",
        "exposure",
        "price_pressure",
    ]
    assert nvda["rates_path"]["edges"]
    assert all(edge.get("invalidation") for edge in nvda["rates_path"]["edges"])
    assert aapl["rates_path"]["status"] == "not_applicable"
    assert nok["rates_path"]["status"] == "not_applicable"
    nvda_main = {row["metric"] for row in nvda["facts"] if row.get("kind") == "macro"}
    aapl_main = {row["metric"] for row in aapl["facts"] if row.get("kind") == "macro"}
    nok_main = {row["metric"] for row in nok["facts"] if row.get("kind") == "macro"}
    assert "cpi" in nvda_main
    assert "us2y" in nvda_main
    assert "cpi" not in aapl_main
    assert "cpi" not in nok_main
    assert "gold" not in nvda_main
    aapl_bg = {row["metric"] for row in aapl["market_background"]}
    assert "cpi" in aapl_bg
    assert "gold" in aapl_bg
    def layer_metrics(view, layer_id):
        layer = next(row for row in view["layers"] if row["id"] == layer_id)
        return {item.get("metric") for item in layer["items"]}
    assert "cpi" in layer_metrics(nvda, "fact")
    assert "cpi" in layer_metrics(nvda, "change")
    assert "cpi" not in layer_metrics(aapl, "fact")
    assert "cpi" not in layer_metrics(aapl, "change")
    assert "cpi" not in layer_metrics(nok, "fact")
    assert "cpi" not in layer_metrics(nok, "change")


def test_vix_is_risk_state_not_stock_direction():
    view = assemble_from_bundle(_bundle("NVDA"))
    risk = view["risk_state"]
    assert risk["metric"] == "vix"
    assert risk["does_not_imply"] == "个股涨跌方向"
    assert risk["affects"] == "risk_state"
    assert "股票" in risk["invalidation"]
    layer_change = next(row for row in view["layers"] if row["id"] == "change")
    assert all(item.get("metric") != "vix" for item in layer_change["items"])


def test_inject_gated_and_per_chain(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENABLE_DECISION_INJECT", raising=False)
    assert inject_allowed() is False
    assert parse_inject_tokens("missing_gold,not_a_token") == frozenset({"missing_gold"})
    intact = assemble_from_bundle(_bundle("NVDA"))
    codes = {row["code"] for row in intact["gaps"]}
    gold_only = assemble_from_bundle(apply_inject(_bundle("NVDA"), ["missing_gold"]))
    nfp_only = assemble_from_bundle(apply_inject(_bundle("NVDA"), ["missing_nfp"]))
    assert "missing_gold" in {row["code"] for row in gold_only["gaps"]}
    assert "missing_nfp" in {row["code"] for row in nfp_only["gaps"]}
    gold_gap = next(row for row in gold_only["gaps"] if row["code"] == "missing_gold")
    nfp_gap = next(row for row in nfp_only["gaps"] if row["code"] == "missing_nfp")
    assert gold_gap["affects_chain"] == "commodity"
    assert nfp_gap["affects_chain"] == "labor"
    assert "missing_cpi" not in {row["code"] for row in gold_only["gaps"]}
    assert intact["overall"]["level"] == gold_only["overall"]["level"] or gold_only["overall"]["level"] != "L0"
    news_only = assemble_from_bundle(apply_inject(_bundle("AAPL"), ["missing_news"]))
    assert all(row["affects_chain"] != "page" for row in news_only["gaps"] if row["code"] == "missing_news")


def test_public_inject_query_cannot_enable(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENABLE_DECISION_INJECT", raising=False)
    monkeypatch.setattr(api, "database", FakeDatabase())
    monkeypatch.setattr("stock_pm.series.collect_live_macro_overlay", _empty_live_overlay)
    monkeypatch.setattr("stock_pm.alpaca.collect_live_daily_bars", lambda *a, **k: ([], set(), {}))
    monkeypatch.setattr("stock_pm.providers.collect_live_earnings", lambda *a, **k: ([], set(), {}))
    body = TestClient(api.app).get("/api/stock/NVDA/decision?inject=missing_nfp,missing_gold").json()
    assert body.get("inject") in (None, [], ())


def test_withhold_strips_percent_forecast():
    pred = withhold_unsourced_prediction(
        {
            "therefore": "当天涨约1%，期间跌幅不超过1%",
            "upside_bound_pct": 1,
            "downside_bound_pct": 1,
            "prediction_ready": True,
            "badge": "两周内补涨约10%",
            "one_liner": "当天涨约1%",
        },
        can_form_direction=False,
    )
    assert pred["direction_withheld"] is True
    assert pred["upside_bound_pct"] is None
    assert "1%" not in (pred["therefore"] or "")
    assert pred["badge"] is None
    assert pred["kind"] == "historical_or_withheld"
    assert pred["upside_price"] is None
    assert "1%" not in json.dumps(pred.get("struct") or {}, ensure_ascii=False)


def test_ui_renders_causal_layers_and_fact_drawer():
    stock = Path("src/stock_pm/static/stock_diag.js").read_text()
    assert "Fact → Change → Expectation → Impact → What changes" in stock
    assert "renderRatesPath" in stock
    assert "renderRiskState" in stock
    assert "market-background" in stock
    assert "fact-drawer" in stock
    assert "sourceLink" in stock
    assert "can_form_direction=false" in stock
    assert "function extraQuery()" in stock
    assert "data-decision-ready" in stock
    assert "next.set(\"inject\", inject)" in stock
    assert "影响方向" in stock
    assert "期限" in stock
    fold_block = stock[stock.index("decision-chain-fold"):]
    assert "renderChainGroups(payload)" in fold_block
    assert stock.index("class=\"causal-flow\"") < stock.index("decision-chain-fold")
    assert "item.metric || item.id" in stock
    html = Path("src/stock_pm/static/stock.html").read_text()
    assert 'id="fact-drawer"' in html
    assert "/static/stock_diag.js" in html
    shell = Path("src/stock_pm/static/shell.js").read_text()
    assert "direction_withheld" in shell


def test_duration_exposure_differs_by_name():
    assert has_duration_exposure(_watch("NVDA"), "NVDA") is True
    assert has_duration_exposure(_watch("AAPL"), "AAPL") is False
    assert has_duration_exposure(_watch("NOK"), "NOK") is False
    path = build_rates_path(
        symbol="AAPL",
        watch=_watch("AAPL"),
        changes=[],
        confirmation=None,
        facts=[],
    )
    assert path["status"] == "not_applicable"
