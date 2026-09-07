from datetime import datetime, timedelta, timezone

from stock_pm.flow import build_segments, infer_sides, spike_windows, zigzag_segments


def _bars(closes: list[float], volume: float = 10_000) -> list[dict]:
    start = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    return [
        {
            "bar_time": start + timedelta(minutes=index),
            "open_price": close,
            "high_price": close + 0.05,
            "low_price": close - 0.05,
            "close_price": close,
            "volume": volume,
        }
        for index, close in enumerate(closes)
    ]


def test_zigzag_splits_v_shape_into_two_segments() -> None:
    closes = [100 - i for i in range(10)] + [92 + i for i in range(10)]
    segments = zigzag_segments(_bars(closes), threshold_pct=1.0)
    assert len(segments) == 2
    (s1, e1), (s2, e2) = segments
    assert s1 == 0 and e1 == 9      # decline bottoms at index 9
    assert s2 == 9 and e2 == 19     # then the rebound


def test_build_segments_metrics_and_large_trade_attribution() -> None:
    closes = [100 - i * 0.5 for i in range(10)] + [95.5 + i * 0.5 for i in range(10)]
    bars = _bars(closes)
    trade_time = bars[2]["bar_time"]
    large = [
        {"trade_time": trade_time, "notional": 400_000, "side_inferred": "sell"},
        {"trade_time": bars[15]["bar_time"], "notional": 600_000, "side_inferred": "buy"},
    ]
    segments = build_segments(bars, large)
    assert len(segments) >= 2
    down = segments[0]
    assert down["direction"] == "down"
    assert down["large_sell_notional"] == 400_000
    up = segments[-1]
    assert up["direction"] == "up"
    assert up["large_buy_notional"] == 600_000
    assert all(seg["vwap_side"] in ("above", "below") for seg in segments)


def test_tick_rule_side_inference() -> None:
    trades = [
        {"price": 100.0},
        {"price": 100.5},   # uptick -> buy
        {"price": 100.5},   # unchanged -> carries buy
        {"price": 100.1},   # downtick -> sell
    ]
    infer_sides(trades)
    assert [t["side_inferred"] for t in trades] == ["unknown", "buy", "buy", "sell"]


def test_spike_windows_merge_adjacent_minutes() -> None:
    bars = _bars([100.0] * 10, volume=1_000)
    bars[3]["volume"] = 10_000
    bars[4]["volume"] = 12_000
    bars[8]["volume"] = 9_000
    windows = spike_windows(bars, baseline=1_000, notional_threshold=1e12)
    assert len(windows) == 2
    assert windows[0][0] == bars[3]["bar_time"]
    assert windows[0][1] == bars[4]["bar_time"] + timedelta(minutes=1)
