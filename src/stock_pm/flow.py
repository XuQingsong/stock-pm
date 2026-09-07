from __future__ import annotations

"""Large-trade and intraday segment analysis (盘面分段量价).

Two-pass collection keeps API volume manageable on the free Alpaca tier:

1. From the day's 1-minute bars already in PostgreSQL, pick "spike" minutes
   whose volume exceeds a multiple of the 20-day average minute volume (or
   whose notional is large in absolute terms).
2. Fetch tick-level trades only for those windows and keep single prints
   with notional >= LARGE_TRADE_NOTIONAL. Trade side is inferred with the
   tick rule and stored as an inference, never as ground truth.

Independently of large trades, the day's 1m bars are segmented with a
ZigZag swing algorithm and each segment gets volume/price metrics.
"""

import argparse
import json
import time as time_module
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .alpaca import AlpacaClient, _bars, _trades
from .config import Settings
from .database import Database

NEW_YORK = ZoneInfo("America/New_York")
SPIKE_VOLUME_MULTIPLIER = 3.0
MAX_WINDOWS_PER_DAY = 40
FLAT_SEGMENT_PCT = 0.05


def zigzag_segments(bars: list[dict], threshold_pct: float) -> list[tuple[int, int]]:
    """Split chronological bars into swing segments (index ranges, inclusive).

    A swing reverses when price retraces `threshold_pct` percent from the
    running extreme. Every bar belongs to exactly one segment.
    """
    closes = [float(bar["close_price"]) for bar in bars]
    if len(closes) < 2:
        return [(0, len(closes) - 1)] if closes else []
    pivots = [0]
    direction: str | None = None
    extreme_index = 0
    for index in range(1, len(closes)):
        price = closes[index]
        extreme = closes[extreme_index]
        if direction is None:
            move = (price / closes[0] - 1) * 100
            if abs(move) >= threshold_pct:
                direction = "up" if move > 0 else "down"
                extreme_index = index
        elif direction == "up":
            if price >= extreme:
                extreme_index = index
            elif (price / extreme - 1) * 100 <= -threshold_pct:
                pivots.append(extreme_index)
                direction = "down"
                extreme_index = index
        else:
            if price <= extreme:
                extreme_index = index
            elif (price / extreme - 1) * 100 >= threshold_pct:
                pivots.append(extreme_index)
                direction = "up"
                extreme_index = index
    last = len(closes) - 1
    if pivots[-1] != last:
        if direction is not None and extreme_index not in (pivots[-1], last):
            pivots.append(extreme_index)
        pivots.append(last)
    return [(pivots[i], pivots[i + 1]) for i in range(len(pivots) - 1)]


def infer_sides(trades: list[dict]) -> None:
    """Tick rule: uptick=buy, downtick=sell, unchanged carries the last side."""
    previous_price: float | None = None
    previous_side = "unknown"
    for trade in trades:
        price = trade["price"]
        if previous_price is None or price == previous_price:
            trade["side_inferred"] = previous_side
        else:
            trade["side_inferred"] = "buy" if price > previous_price else "sell"
        previous_price = price
        previous_side = trade["side_inferred"]


def build_segments(bars: list[dict], large_trades: list[dict]) -> list[dict[str, Any]]:
    """Compute per-segment price/volume metrics from chronological 1m bars."""
    if len(bars) < 5:
        return []
    closes = [float(bar["close_price"]) for bar in bars]
    highs = [float(bar["high_price"] or bar["close_price"]) for bar in bars]
    lows = [float(bar["low_price"] or bar["close_price"]) for bar in bars]
    volumes = [float(bar.get("volume") or 0) for bar in bars]
    day_range_pct = (max(highs) - min(lows)) / closes[0] * 100 if closes[0] else 0
    threshold = max(0.3, 0.15 * day_range_pct)

    cumulative_pv = cumulative_volume = 0.0
    vwaps = []
    for index, bar in enumerate(bars):
        typical = (highs[index] + lows[index] + closes[index]) / 3
        cumulative_pv += typical * volumes[index]
        cumulative_volume += volumes[index]
        vwaps.append(cumulative_pv / cumulative_volume if cumulative_volume else closes[index])

    day_avg_minute_volume = (sum(volumes) / len(volumes)) if volumes else 0
    segments = []
    for seg_no, (start, end) in enumerate(zigzag_segments(bars, threshold), start=1):
        start_price, end_price = closes[start], closes[end]
        change_pct = (end_price / start_price - 1) * 100 if start_price else 0
        seg_volume = sum(volumes[start:end + 1])
        minutes = end - start + 1
        rel_volume = (
            (seg_volume / minutes) / day_avg_minute_volume
            if day_avg_minute_volume and minutes
            else None
        )
        start_time = bars[start]["bar_time"]
        end_time = bars[end]["bar_time"]
        buy = sell = 0.0
        count = 0
        for trade in large_trades:
            if start_time <= trade["trade_time"] <= end_time:
                count += 1
                if trade["side_inferred"] == "buy":
                    buy += trade["notional"]
                elif trade["side_inferred"] == "sell":
                    sell += trade["notional"]
        segments.append(
            {
                "seg_no": seg_no,
                "start_time": start_time,
                "end_time": end_time,
                "direction": (
                    "flat" if abs(change_pct) < FLAT_SEGMENT_PCT
                    else "up" if change_pct > 0 else "down"
                ),
                "start_price": start_price,
                "end_price": end_price,
                "change_pct": round(change_pct, 3),
                "volume": seg_volume,
                "rel_volume": round(rel_volume, 2) if rel_volume is not None else None,
                "vwap_side": "above" if end_price >= vwaps[end] else "below",
                "large_buy_notional": round(buy, 2),
                "large_sell_notional": round(sell, 2),
                "large_trade_count": count,
            }
        )
    return segments


def spike_windows(bars: list[dict], baseline: float, notional_threshold: float) -> list[tuple[datetime, datetime]]:
    """Merge adjacent spike minutes into fetch windows, capped per day."""
    flagged = []
    for bar in bars:
        volume = float(bar.get("volume") or 0)
        close = float(bar["close_price"])
        if (baseline and volume >= SPIKE_VOLUME_MULTIPLIER * baseline) or (
            close * volume >= 5 * notional_threshold
        ):
            flagged.append((bar["bar_time"], volume))
    flagged.sort(key=lambda item: item[1], reverse=True)
    flagged = sorted(stamp for stamp, _ in flagged[:MAX_WINDOWS_PER_DAY])
    windows: list[tuple[datetime, datetime]] = []
    for stamp in flagged:
        end = stamp + timedelta(minutes=1)
        if windows and stamp <= windows[-1][1]:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((stamp, end))
    return windows


def _minute_baseline(database: Database, symbol: str, trade_date: date) -> float:
    rows = database.fetch_all(
        """
        SELECT AVG(volume) AS avg_volume FROM price_bars
        WHERE symbol = %s AND bar_size = '1m'
          AND bar_time::date BETWEEN %s AND %s
        """,
        (symbol, trade_date - timedelta(days=28), trade_date - timedelta(days=1)),
    )
    return float(rows[0]["avg_volume"] or 0) if rows else 0.0


def analyze_symbol_day(
    database: Database,
    client: AlpacaClient,
    symbol: str,
    trade_date: date,
    notional_threshold: float,
) -> dict[str, int]:
    day_bars = database.fetch_all(
        """
        SELECT bar_time, open_price, high_price, low_price, close_price, volume
        FROM price_bars
        WHERE symbol = %s AND bar_size = '1m' AND bar_time::date = %s
        ORDER BY bar_time
        """,
        (symbol, trade_date),
    )
    if len(day_bars) < 5:
        return {"bars": len(day_bars), "large_trades": 0, "segments": 0}

    baseline = _minute_baseline(database, symbol, trade_date)
    if not baseline:
        volumes = sorted(float(bar.get("volume") or 0) for bar in day_bars)
        baseline = volumes[len(volumes) // 2] if volumes else 0

    large: list[dict] = []
    for window_start, window_end in spike_windows(day_bars, baseline, notional_threshold):
        try:
            trades = _trades(client, symbol, window_start, window_end)
        except Exception:
            continue
        infer_sides(trades)
        for trade in trades:
            if trade["notional"] >= notional_threshold:
                large.append({**trade, "symbol": symbol})
        time_module.sleep(0.35)

    database.store_large_trades(large)
    for trade in large:
        if trade["notional"] >= 5 * notional_threshold:
            database.store_event(
                {
                    "symbol": symbol,
                    "event_time": trade["trade_time"].isoformat(),
                    "event_type": "large_trade",
                    "severity": "high",
                    "title": f"大额成交 ${trade['notional']:,.0f} · {trade['side_inferred']}(推断)",
                    "details": {
                        "price": trade["price"],
                        "shares": trade["size"],
                        "notional": trade["notional"],
                        "direction": f"{trade['side_inferred']} (tick rule 推断)",
                    },
                    "source": "Alpaca SIP trades",
                    "unique_key": (
                        f"alpaca-trade:{symbol}:{trade['trade_time'].isoformat()}"
                        f":{trade['price']}:{trade['size']}"
                    ),
                }
            )

    segments = build_segments(day_bars, large)
    database.store_segments(symbol, trade_date.isoformat(), segments)
    return {"bars": len(day_bars), "large_trades": len(large), "segments": len(segments)}


def ensure_minute_bars(
    database: Database, client: AlpacaClient, symbols: list[str], start_date: date, end_date: date
) -> None:
    """Fetch 1m bars for the range and upsert them, clamped to the 15-min delay."""
    start = datetime.combine(start_date, datetime.min.time(), NEW_YORK).astimezone(timezone.utc)
    end = datetime.combine(end_date, datetime.max.time(), NEW_YORK).astimezone(timezone.utc)
    end = min(end, datetime.now(timezone.utc) - timedelta(minutes=16))
    if end <= start:
        return
    bars = _bars(client, symbols, "1Min", start, end)
    payload = {
        "source": "alpaca",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "history": [
            {
                "symbol": symbol,
                "bar_size": "1m",
                "source": f"alpaca_{client.settings.alpaca_bars_feed}_delayed",
                "bars": rows,
            }
            for symbol, rows in bars.items()
            if rows
        ],
    }
    if payload["history"]:
        database.ingest(payload)


def run(days: int = 1, target_date: str | None = None, symbols: list[str] | None = None) -> dict:
    settings = Settings()
    client = AlpacaClient(settings)
    database = Database(settings)
    results: dict[str, Any] = {}
    try:
        database.initialize()
        requested = database._watchlist_symbols(symbols)
        if target_date:
            dates = [date.fromisoformat(target_date)]
        else:
            today = datetime.now(NEW_YORK).date()
            dates = [today - timedelta(days=offset) for offset in range(days * 2)]
            dates = [d for d in dates if d.weekday() < 5][:days]
            dates.reverse()
        ensure_minute_bars(database, client, requested, min(dates), max(dates))
        for trade_date in dates:
            for symbol in requested:
                key = f"{symbol}:{trade_date.isoformat()}"
                try:
                    results[key] = analyze_symbol_day(
                        database, client, symbol, trade_date, settings.large_trade_notional
                    )
                except Exception as exc:
                    results[key] = {"error": str(exc)}
    finally:
        database.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze large trades and intraday segments")
    parser.add_argument("--days", type=int, default=1, help="Trading days to analyze, counting back from today")
    parser.add_argument("--date", help="Analyze a single date (YYYY-MM-DD) instead")
    parser.add_argument("--symbols", nargs="*")
    args = parser.parse_args()
    print(json.dumps(run(args.days, args.date, args.symbols), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
