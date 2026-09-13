from datetime import datetime, timezone

import pytest

from stock_pm.alpaca import (
    AlpacaError,
    _bars,
    collect_live_daily_bars,
    daily_bars_http_source,
    market_is_collectible,
    parse_option_symbol,
)
from stock_pm.config import Settings
from stock_pm.decision.health import build_data_health


class _FakeClient:
    def __init__(self, feed: str = "sip") -> None:
        self.settings = Settings(
            alpaca_api_key_id="k",
            alpaca_api_secret_key="s",
            alpaca_bars_feed=feed,
        )
        self.params = None

    def get(self, base, path, params=None):
        self.params = params
        return {"bars": {}}


def test_parse_option_symbol() -> None:
    underlying, expiry, side, strike = parse_option_symbol("AAPL260918C00250000")
    assert (underlying, expiry.isoformat(), side, strike) == ("AAPL", "2026-09-18", "C", 250.0)


def test_parse_option_symbol_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        parse_option_symbol("AAPL-CALL")


def test_market_window_uses_new_york_time() -> None:
    assert market_is_collectible(datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc))
    assert not market_is_collectible(datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc))


def test_bars_use_configured_data_feed() -> None:
    client = _FakeClient("sip")
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    _bars(client, ["AAPL"], "1Day", now, now)
    assert client.params["feed"] == "sip"
    assert client.params["adjustment"] == "split"


def test_live_daily_bars_unconfigured() -> None:
    bars, errors, report = collect_live_daily_bars("NVDA", Settings(alpaca_api_key_id="", alpaca_api_secret_key=""))
    rec = report["daily_price_bars"]
    assert bars == []
    assert errors == set()
    assert rec["status"] == "not_configured"
    assert rec["series_or_symbol"] == "NVDA"
    assert rec["value"] is None
    assert rec["http_source"].startswith("https://data.alpaca.markets/v2/stocks/bars")
    assert "apikey=" not in rec["http_source"].lower()
    assert rec["required_env"] == "ALPACA_API_KEY_ID+ALPACA_API_SECRET_KEY"


def test_live_daily_bars_ok(monkeypatch) -> None:
    def fake_bars(client, symbols, timeframe, start, end):
        assert symbols == ["NVDA"]
        assert timeframe == "1Day"
        return {
            "NVDA": [
                {
                    "bar_time": "2026-09-10T20:00:00+00:00",
                    "open_price": 216.0,
                    "high_price": 218.0,
                    "low_price": 215.0,
                    "close_price": 217.1,
                },
                {
                    "bar_time": "2026-09-11T20:00:00+00:00",
                    "open_price": 217.0,
                    "high_price": 219.5,
                    "low_price": 216.4,
                    "close_price": 218.29,
                },
            ]
        }

    monkeypatch.setattr("stock_pm.alpaca._bars", fake_bars)
    bars, errors, report = collect_live_daily_bars(
        "nvda",
        Settings(alpaca_api_key_id="set", alpaca_api_secret_key="set", alpaca_bars_feed="sip"),
    )
    rec = report["daily_price_bars"]
    assert errors == set()
    assert bars[0]["as_of"] == "2026-09-11"
    assert bars[0]["close_price"] == 218.29
    assert rec["status"] == "ok"
    assert rec["as_of"] == "2026-09-11"
    assert rec["value"] == 218.29
    assert rec["unit"] == "USD"
    assert rec["source"] == "alpaca_sip"
    assert rec["http_source"] == daily_bars_http_source("NVDA", "sip")
    health = build_data_health(
        {"symbol": "NVDA", "bars": bars, "earnings": [], "macro_events": []},
        settings=Settings(alpaca_api_key_id="set", alpaca_api_secret_key="set"),
    )
    row = next(item for item in health["datasets"] if item["dataset"] == "daily_price_bars")
    assert row["status"] == "ok"
    assert row["as_of"] == "2026-09-11"
    assert row["value"] == 218.29
    assert row["unit"] == "USD"
    assert row["series_or_symbol"] == "NVDA"


def test_live_daily_bars_query_error(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AlpacaError("Alpaca request failed for /v2/stocks/bars: forbidden")

    monkeypatch.setattr("stock_pm.alpaca._bars", boom)
    bars, errors, report = collect_live_daily_bars(
        "NVDA",
        Settings(alpaca_api_key_id="set", alpaca_api_secret_key="set"),
    )
    assert bars == []
    assert "daily_price_bars" in errors
    assert report["daily_price_bars"]["status"] == "error"
    assert report["daily_price_bars"]["reason_code"] == "query_error"
