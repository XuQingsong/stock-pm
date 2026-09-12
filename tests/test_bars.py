from __future__ import annotations

from datetime import datetime, timezone

from stock_pm.bars import (
    DAILY_ADJUSTMENT,
    decorate_bar,
    is_valid_ohlc,
    last_completed_session_end,
    partition_ohlc_rows,
    usable_daily_bars,
)


def test_invalid_close_above_high_is_rejected():
    row = {
        "open_price": 116.8,
        "high_price": 118.5,
        "low_price": 115.0,
        "close_price": 122.0,
        "bar_time": "2026-09-10T20:00:00+00:00",
    }
    assert is_valid_ohlc(row) is False
    assert usable_daily_bars([row]) == []


def test_frozen_low_above_open_is_rejected():
    row = {
        "open_price": 113.1,
        "high_price": 114.8,
        "low_price": 114.84,
        "close_price": 113.5,
        "bar_time": "2026-09-03T20:00:00+00:00",
    }
    assert is_valid_ohlc(row) is False


def test_decorate_bar_tags_split_adjustment_and_ny_session():
    row = decorate_bar(
        {
            "o": 116.0,
            "h": 118.0,
            "l": 115.0,
            "c": 117.0,
            "t": "2026-09-10T20:00:00+00:00",
        },
        fetched_at="2026-09-11T01:00:00+00:00",
        source="alpaca_sip",
    )
    assert row["adjustment"] == DAILY_ADJUSTMENT
    assert row["session"] == "America/New_York"
    assert row["session_date"] == "2026-09-10"
    assert row["trading_day"] is True
    assert row["status"] == "ok"
    assert row["fetched_at"] == "2026-09-11T01:00:00+00:00"


def test_partition_keeps_valid_historical_bars():
    valid_old = {
        "symbol": "NVDA",
        "bar_size": "1d",
        "bar_time": "2025-01-15T21:00:00+00:00",
        "open_price": 130.0,
        "high_price": 132.0,
        "low_price": 129.0,
        "close_price": 131.0,
    }
    valid_recent = {
        "symbol": "NVDA",
        "bar_size": "1d",
        "bar_time": "2026-09-09T20:00:00+00:00",
        "open_price": 115.88,
        "high_price": 117.62,
        "low_price": 114.84,
        "close_price": 116.35,
    }
    invalid = {
        "symbol": "NVDA",
        "bar_size": "1d",
        "bar_time": "2026-09-10T20:00:00+00:00",
        "open_price": 116.8,
        "high_price": 118.5,
        "low_price": 115.0,
        "close_price": 122.0,
    }
    parts = partition_ohlc_rows([valid_old, valid_recent, invalid])
    assert {row["bar_time"] for row in parts["valid"]} == {
        valid_old["bar_time"],
        valid_recent["bar_time"],
    }
    assert [row["bar_time"] for row in parts["invalid"]] == [invalid["bar_time"]]


def test_last_completed_session_skips_weekend():
    saturday = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
    end = last_completed_session_end(saturday)
    assert end.astimezone(timezone.utc).date().isoformat() == "2026-09-11"
