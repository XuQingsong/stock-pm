from datetime import datetime, timedelta, timezone

from stock_pm.review import analyze_bars


def _bars(latest_close: float = 125, latest_volume: float = 3_000_000) -> list[dict]:
    start = datetime(2026, 9, 4, tzinfo=timezone.utc)
    rows = []
    for index in range(80):
        close = latest_close if index == 0 else 100 + (79 - index) * 0.25
        rows.append(
            {
                "bar_time": start - timedelta(days=index),
                "open_price": close - 0.5,
                "high_price": close + 1,
                "low_price": close - 1,
                "close_price": close,
                "volume": latest_volume if index == 0 else 1_000_000,
            }
        )
    return rows


def test_breakout_requires_close_and_volume_confirmation() -> None:
    result = analyze_bars(_bars())
    assert result["breakout"] == "放量有效突破"
    assert result["relative_volume"] == 3
    assert result["support"] < result["close"]


def test_volume_profile_and_flow_are_exposed() -> None:
    result = analyze_bars(_bars(latest_close=118, latest_volume=800_000))
    assert result["poc_60d"] is not None
    assert result["value_area_low"] <= result["value_area_high"]
    assert 0 <= result["volume_below_price_pct"] <= 100
    assert result["flow"]
