"""Alpha Vantage gold adapter. FRED GOLDPMGBD228NLBM is historical only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_pm.config import Settings
from stock_pm.decision.health import (
    REASON_DEPRECATED,
    REASON_SOURCE_NOT_CONFIGURED,
    REASON_UPSTREAM_UNAVAILABLE,
    build_data_health,
)
from stock_pm.fetch import FetchError, FetchResult
from stock_pm.gold import (
    FRED_GOLD_HISTORICAL,
    GOLD_ENV_VAR,
    GOLD_SYMBOL,
    build_gold_event,
    fetch_alpha_vantage_gold,
    fred_gold_historical_record,
    is_deprecated_fred_gold,
    parse_alpha_vantage_gold,
    sync_live_gold,
)
from stock_pm.series import FRED_MARKET_SERIES, collect_live_macro_overlay, merge_live_macros, normalized_record


FETCHED = "2026-09-12T06:20:00+00:00"
FIXTURE = Path("tests/fixtures/av_gold_xau.json")


def _av_ok(**kwargs) -> FetchResult:
    payload = json.loads(FIXTURE.read_text())
    return FetchResult(
        payload=payload,
        status=kwargs.get("status", "ok"),
        reason_code=kwargs.get("reason_code", "within_threshold"),
        fetched_at=FETCHED,
        from_cache=kwargs.get("from_cache", False),
        http_source="https://www.alphavantage.co/query?function=GOLD_SILVER_HISTORY&symbol=XAU&interval=daily",
        transport="alpha_vantage",
    )


def test_official_history_price_field_parses():
    rows = parse_alpha_vantage_gold(
        {
            "nominal": "XAUUSD",
            "data": [
                {"date": "2026-09-11", "price": "4318.8913924063"},
                {"date": "2026-09-10", "price": "4300.1"},
            ],
        }
    )
    assert rows[0]["period"] == "2026-09-11"
    assert abs(rows[0]["value"] - 4318.8913924063) < 1e-6


def test_recorded_av_gold_fixture_is_labeled():
    payload = json.loads(FIXTURE.read_text())
    assert "recorded fixture" in payload["label"]
    assert "not a live" in payload["label"]
    rows = parse_alpha_vantage_gold(payload)
    assert rows[0]["period"] == "2026-09-11"
    assert rows[0]["value"] == 2348.5


def test_gold_ok_uses_alpha_vantage_history(monkeypatch):
    monkeypatch.setattr("stock_pm.gold.json_get", lambda *a, **k: _av_ok())
    events, rec = sync_live_gold(Settings(alpha_vantage_api_key="set"))
    assert rec["status"] == "ok"
    assert rec["source"] == "alpha_vantage"
    assert rec["series_or_symbol"] == GOLD_SYMBOL
    assert rec["as_of"] == "2026-09-11"
    assert rec["value"] == 2348.5
    assert rec["unit"] == "USD/oz"
    assert rec["required_env"] == GOLD_ENV_VAR
    assert rec["historical_status"] == "upstream_unavailable"
    assert rec["historical_reason_code"] == "deprecated"
    assert rec["historical_series_or_symbol"] == "GOLDPMGBD228NLBM"
    assert rec["http_source"]
    assert "apikey" not in rec["http_source"]
    assert events[0]["source"] == "alpha_vantage"
    norm = normalized_record(events[0])
    assert norm["series_or_symbol"] == "XAU"
    assert norm["as_of"] != norm["observed_at"]
    assert norm["value"] == 2348.5


def test_gold_unconfigured_names_env_var():
    events, rec = sync_live_gold(Settings(alpha_vantage_api_key=""))
    assert events == []
    assert rec["status"] == "not_configured"
    assert rec["reason_code"] == "source_not_configured"
    assert rec["value"] is None
    assert rec["required_env"] == "ALPHA_VANTAGE_API_KEY"
    assert GOLD_ENV_VAR in (rec.get("note") or "")
    health = build_data_health(
        {"symbol": "NVDA", "bars": [], "earnings": [], "macro_events": []},
        settings=Settings(alpha_vantage_api_key=""),
    )
    gold = next(row for row in health["datasets"] if row["dataset"] == "macro_gold")
    assert gold["status"] == "not_configured"
    assert gold["reason_code"] == REASON_SOURCE_NOT_CONFIGURED
    assert gold["series_or_symbol"] == "XAU"
    assert gold["value"] is None
    assert gold["required_env"] == "ALPHA_VANTAGE_API_KEY"
    assert "ALPHA_VANTAGE_API_KEY" in gold["next_action"]


def test_fred_gold_is_upstream_unavailable_deprecated_not_current_price():
    rec = fred_gold_historical_record(fetched_at=FETCHED)
    assert rec["status"] == "upstream_unavailable"
    assert rec["reason_code"] == "deprecated"
    assert rec["value"] is None
    assert rec["series_or_symbol"] == "GOLDPMGBD228NLBM"
    stale = {
        "event_type": "gold",
        "source": "FRED",
        "series_or_symbol": "GOLDPMGBD228NLBM",
        "actual": 1800.0,
        "value": 1800.0,
        "as_of": "2022-01-28",
        "event_time": "2022-01-28T00:00:00+00:00",
        "observed_at": "2022-01-31T00:00:00+00:00",
        "unit": "USD/oz",
    }
    assert is_deprecated_fred_gold(stale)
    health = build_data_health(
        {"symbol": "NVDA", "bars": [], "earnings": [], "macro_events": [stale]},
        settings=Settings(alpha_vantage_api_key=""),
    )
    gold = next(row for row in health["datasets"] if row["dataset"] == "macro_gold")
    assert gold["status"] == "not_configured"
    assert gold["value"] is None
    assert gold["value"] != 1800.0
    assert gold["historical_status"] == REASON_UPSTREAM_UNAVAILABLE
    assert gold["historical_reason_code"] == REASON_DEPRECATED
    merged = merge_live_macros({"macro_events": [stale], "synthetic": False}, [])
    assert merged["macro_events"] == []


def test_gold_stale_cache(monkeypatch):
    monkeypatch.setattr(
        "stock_pm.gold.json_get",
        lambda *a, **k: _av_ok(status="stale", reason_code="record_stale", from_cache=True),
    )
    _events, rec = sync_live_gold(Settings(alpha_vantage_api_key="set"))
    assert rec["status"] == "stale"
    assert rec["from_cache"] is True
    assert rec["as_of"] == "2026-09-11"
    assert rec["value"] == 2348.5


def test_gold_upstream_failure_does_not_use_fred_price(monkeypatch):
    def boom(*_a, **_k):
        raise FetchError("query_error", "HTTP Error 503")

    monkeypatch.setattr("stock_pm.gold.json_get", boom)
    events, rec = sync_live_gold(Settings(alpha_vantage_api_key="set"))
    assert events == []
    assert rec["status"] == "error"
    assert rec["value"] is None
    assert rec["series_or_symbol"] == "XAU"
    assert rec["historical_series_or_symbol"] == "GOLDPMGBD228NLBM"


def test_gold_parse_errors():
    with pytest.raises(FetchError) as exc:
        parse_alpha_vantage_gold("nope")
    assert exc.value.reason_code == "record_invalid"
    with pytest.raises(FetchError) as exc:
        parse_alpha_vantage_gold({"data": {"date": "2026-09-11"}})
    assert exc.value.reason_code == "record_invalid"
    with pytest.raises(FetchError) as exc:
        parse_alpha_vantage_gold({"Note": "thank you"})
    assert exc.value.reason_code == "rate_limited"
    with pytest.raises(FetchError) as exc:
        parse_alpha_vantage_gold({"data": [{"date": "soon", "value": "1"}]})
    assert exc.value.reason_code == "record_invalid"


def test_fetch_strips_apikey_from_http_source(monkeypatch):
    def fake_json(url, **kwargs):
        assert "apikey=" in url
        return _av_ok()

    monkeypatch.setattr("stock_pm.gold.json_get", fake_json)
    result = fetch_alpha_vantage_gold("super-secret-key")
    assert "apikey" not in (result.http_source or "")
    assert "super-secret-key" not in (result.http_source or "")
    assert result.http_source.endswith("symbol=XAU&interval=daily")


def test_overlay_gold_unconfigured_does_not_break_other_macros(monkeypatch):
    def fake_text(url, **kwargs):
        series_id = next(
            spec["series_id"] for spec in FRED_MARKET_SERIES.values() if spec["series_id"] in url
        )
        period = "2026-08-01" if series_id == "CPIAUCSL" else "2026-09-10"
        return FetchResult(
            payload=f"observation_date,{series_id}\n{period},2.5\n",
            status="ok",
            reason_code="within_threshold",
            fetched_at=FETCHED,
            from_cache=False,
            http_source=url,
            transport="text",
        )

    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    events, errors, report = collect_live_macro_overlay(Settings(fred_api_key="", alpha_vantage_api_key=""))
    assert "macro_gold" not in errors
    assert report["series"]["gold"]["status"] == "not_configured"
    assert report["series"]["gold"]["value"] is None
    assert report["series"]["gold_fred_historical"]["status"] == "upstream_unavailable"
    assert report["series"]["gold_fred_historical"]["value"] is None
    assert report["series"]["cpi"]["status"] == "ok"
    assert all(row.get("event_type") != "gold" for row in events)
    assert FRED_GOLD_HISTORICAL["series_id"] == "GOLDPMGBD228NLBM"


def test_build_gold_event_keeps_contract():
    event = build_gold_event(
        {"period": "2026-09-11", "value": 2348.5, "unit": "USD per troy ounce"},
        fetched_at=FETCHED,
        from_cache=False,
        http_source="https://www.alphavantage.co/query?function=GOLD_SILVER_HISTORY&symbol=XAU&interval=daily",
        transport="alpha_vantage",
    )
    rec = normalized_record(event)
    assert rec["source"] == "alpha_vantage"
    assert rec["series_or_symbol"] == "XAU"
    assert rec["unit"] == "USD/oz"
    assert rec["as_of"] == "2026-09-11"
    assert rec["status"] == "ok"
    assert event["historical_status"] == "upstream_unavailable"
