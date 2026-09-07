from datetime import datetime, timezone

import pytest

from stock_pm.alpaca import _bars, market_is_collectible, parse_option_symbol
from stock_pm.config import Settings


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
