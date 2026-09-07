from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .database import Database


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _volume_profile(bars: list[dict], periods: int = 60, bins: int = 24) -> dict[str, float | None]:
    sample = bars[:periods]
    points = []
    for row in sample:
        high, low, close, volume = (float(row.get(key) or 0) for key in ("high_price", "low_price", "close_price", "volume"))
        if close > 0 and volume > 0:
            points.append(((high + low + close) / 3, volume))
    if not points:
        return {"poc": None, "value_low": None, "value_high": None, "volume_below_pct": None}
    low_price, high_price = min(p[0] for p in points), max(p[0] for p in points)
    if high_price == low_price:
        return {"poc": low_price, "value_low": low_price, "value_high": high_price, "volume_below_pct": 100.0}
    width = (high_price - low_price) / bins
    buckets = [0.0] * bins
    for price, volume in points:
        index = min(bins - 1, int((price - low_price) / width))
        buckets[index] += volume
    poc_index = max(range(bins), key=buckets.__getitem__)
    left = right = poc_index
    selected_volume = buckets[poc_index]
    target = sum(buckets) * 0.70
    while selected_volume < target and (left > 0 or right < bins - 1):
        left_volume = buckets[left - 1] if left > 0 else -1
        right_volume = buckets[right + 1] if right < bins - 1 else -1
        if right_volume >= left_volume:
            right += 1
            selected_volume += buckets[right]
        else:
            left -= 1
            selected_volume += buckets[left]
    latest_close = float(sample[0]["close_price"])
    below = sum(volume for price, volume in points if price <= latest_close)
    total = sum(volume for _, volume in points)
    return {
        "poc": low_price + (poc_index + 0.5) * width,
        "value_low": low_price + left * width,
        "value_high": low_price + (right + 1) * width,
        "volume_below_pct": below / total * 100 if total else None,
    }


def _money_flow(bars: list[dict], periods: int = 20) -> tuple[float | None, float | None]:
    sample = bars[:periods]
    mfv_total = volume_total = 0.0
    for row in sample:
        high, low, close, volume = (float(row.get(key) or 0) for key in ("high_price", "low_price", "close_price", "volume"))
        if high > low and volume > 0:
            mfv_total += ((2 * close - high - low) / (high - low)) * volume
            volume_total += volume
    cmf = mfv_total / volume_total if volume_total else None

    chronological = list(reversed(bars[:30]))
    obv = [0.0]
    for prior, current in zip(chronological, chronological[1:]):
        volume = float(current.get("volume") or 0)
        direction = 1 if current["close_price"] > prior["close_price"] else -1 if current["close_price"] < prior["close_price"] else 0
        obv.append(obv[-1] + direction * volume)
    recent_volume = sum(float(row.get("volume") or 0) for row in bars[:5])
    obv_change = (obv[-1] - obv[-6]) / recent_volume if len(obv) >= 6 and recent_volume else None
    return cmf, obv_change


def _option_position(database: Database, symbol: str) -> dict[str, Any]:
    rows = database.option_wall(symbol)
    if not rows:
        return {"rows": [], "call_wall": None, "put_wall": None, "put_call_ratio": None}
    weight = lambda row, side: float(row[f"{side}_open_interest"] or row[f"{side}_volume"] or 0)
    call_wall = max(rows, key=lambda row: weight(row, "call"))
    put_wall = max(rows, key=lambda row: weight(row, "put"))
    call_total = sum(weight(row, "call") for row in rows)
    put_total = sum(weight(row, "put") for row in rows)
    return {
        "rows": rows, "expiration": str(rows[0]["expiration_date"]),
        "call_wall": float(call_wall["strike"]), "put_wall": float(put_wall["strike"]),
        "put_call_ratio": put_total / call_total if call_total else None,
    }


def analyze_bars(bars: list[dict]) -> dict[str, Any]:
    if len(bars) < 20:
        raise ValueError("At least 20 daily bars are required")
    close = float(bars[0]["close_price"])
    prior_close = float(bars[1]["close_price"])
    high, low, open_price = (float(bars[0][key]) for key in ("high_price", "low_price", "open_price"))
    volume = float(bars[0].get("volume") or 0)
    prior_volumes = [float(row.get("volume") or 0) for row in bars[1:21] if row.get("volume") is not None]
    average_volume = _mean(prior_volumes) or 0
    relative_volume = volume / average_volume if average_volume else None
    day_change = (close / prior_close - 1) * 100 if prior_close else None
    gap = (open_price / prior_close - 1) * 100 if prior_close else None
    close_location = (close - low) / (high - low) if high > low else 0.5
    upper_wick = (high - max(open_price, close)) / (high - low) if high > low else 0
    lower_wick = (min(open_price, close) - low) / (high - low) if high > low else 0

    true_ranges = []
    for current, prior in zip(bars[:21], bars[1:22]):
        h, l, pc = float(current["high_price"]), float(current["low_price"]), float(prior["close_price"])
        true_ranges.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr20 = _mean(true_ranges[:20]) or 0
    prior_high = max(float(row["high_price"]) for row in bars[1:21])
    prior_low = min(float(row["low_price"]) for row in bars[1:21])

    threshold = atr20 * 0.10
    if close > prior_high + threshold:
        breakout = "放量有效突破" if (relative_volume or 0) >= 1.2 else "缩量突破待确认"
    elif high > prior_high and close <= prior_high:
        breakout = "冲高突破失败"
    elif close < prior_low - threshold:
        breakout = "放量有效跌破" if (relative_volume or 0) >= 1.2 else "缩量跌破待确认"
    elif low < prior_low and close >= prior_low:
        breakout = "跌破后收回"
    else:
        breakout = "区间内"

    if (relative_volume or 0) >= 1.0 and (day_change or 0) >= 3 and close_location >= 0.75:
        tape = "大幅上攻且收盘靠近最高价，成交量未萎缩，买盘占优"
    elif (relative_volume or 0) >= 1.0 and (day_change or 0) <= -3 and close_location <= 0.25:
        tape = "大幅下跌且收盘靠近最低价，成交量未萎缩，卖盘占优"
    elif (relative_volume or 0) >= 1.4 and (day_change or 0) > 0.8 and close_location >= 0.70:
        tape = "放量上攻，收盘靠近最高价，买盘主导"
    elif (relative_volume or 0) >= 1.4 and (day_change or 0) < -0.8 and close_location <= 0.30:
        tape = "放量下杀，收盘靠近最低价，卖盘主导"
    elif (relative_volume or 0) >= 1.3 and upper_wick >= 0.35:
        tape = "放量冲高回落，上方抛压明显"
    elif (relative_volume or 0) >= 1.3 and lower_wick >= 0.35:
        tape = "放量探底回升，下方出现承接"
    elif (relative_volume or 0) < 0.75:
        tape = "缩量交易，方向信号可信度较低"
    else:
        tape = "量价未出现显著单边失衡"

    cmf20, obv_change = _money_flow(bars)
    if cmf20 is not None and cmf20 >= 0.10 and (obv_change or 0) > 0:
        flow = "持续吸筹代理信号"
    elif cmf20 is not None and cmf20 <= -0.10 and (obv_change or 0) < 0:
        flow = "持续派发代理信号"
    elif cmf20 is not None and cmf20 > 0:
        flow = "资金流略偏正"
    elif cmf20 is not None and cmf20 < 0:
        flow = "资金流略偏负"
    else:
        flow = "资金流中性"

    profile = _volume_profile(bars)
    def typical_vwap(sample: list[dict]) -> float | None:
        total_volume = sum(float(row.get("volume") or 0) for row in sample)
        return sum(((float(row["high_price"]) + float(row["low_price"]) + float(row["close_price"])) / 3) * float(row.get("volume") or 0) for row in sample) / total_volume if total_volume else None
    avwap20, avwap60 = typical_vwap(bars[:20]), typical_vwap(bars[:60])
    moving_average = lambda n: _mean([float(row["close_price"]) for row in bars[:n]]) if len(bars) >= n else None
    ma20, ma50, ma200 = moving_average(20), moving_average(50), moving_average(200)

    candidate_supports = [prior_low, profile["value_low"], profile["poc"], avwap20, ma20, ma50]
    candidate_resistances = [prior_high, profile["value_high"], profile["poc"], avwap20, ma20, ma50]
    supports = sorted({round(float(x), 4) for x in candidate_supports if x is not None and float(x) < close}, reverse=True)
    resistances = sorted({round(float(x), 4) for x in candidate_resistances if x is not None and float(x) > close})
    support = supports[0] if supports else prior_low
    resistance = resistances[0] if resistances else prior_high
    if low <= support <= close and close_location >= 0.55:
        support_test = "盘中测试支撑后收回"
    elif close < support:
        support_test = "收盘跌破最近支撑"
    else:
        support_test = "未测试最近支撑"

    volume_below = profile["volume_below_pct"]
    if volume_below is not None and volume_below >= 70:
        position = "大部分60日成交筹码处于浮盈区，趋势占优但需防获利回吐"
    elif volume_below is not None and volume_below <= 30:
        position = "大部分60日成交筹码位于现价上方，套牢抛压较重"
    else:
        position = "现价位于60日主要成本分布中部，多空仍在争夺"

    score = 0
    score += 15 if close > (avwap20 or close) else -15
    score += 15 if (cmf20 or 0) >= 0.10 else -15 if (cmf20 or 0) <= -0.10 else 0
    score += 10 if (obv_change or 0) > 0.10 else -10 if (obv_change or 0) < -0.10 else 0
    score += 25 if breakout == "放量有效突破" else -25 if breakout == "放量有效跌破" else 0
    score += 10 if profile["poc"] and close > profile["poc"] else -10
    score += 10 if ma50 and close > ma50 else -10 if ma50 else 0
    score = max(-100, min(100, score))
    bias = "偏多" if score >= 25 else "偏空" if score <= -25 else "中性"

    return {
        "close": close, "day_change_pct": day_change, "gap_pct": gap,
        "relative_volume": relative_volume, "close_location": close_location,
        "atr20": atr20, "prior_high_20d": prior_high, "prior_low_20d": prior_low,
        "breakout": breakout, "tape": tape, "cmf20": cmf20,
        "obv_5d_normalized": obv_change, "flow": flow,
        "poc_60d": profile["poc"], "value_area_low": profile["value_low"],
        "value_area_high": profile["value_high"], "volume_below_price_pct": volume_below,
        "avwap20": avwap20, "avwap60": avwap60, "ma20": ma20, "ma50": ma50, "ma200": ma200,
        "support": support, "resistance": resistance, "support_test": support_test,
        "support_levels": supports[:3], "resistance_levels": resistances[:3],
        "position": position, "score": score, "bias": bias,
    }


def generate_review(database: Database, symbol: str) -> dict | None:
    bars = database.fetch_all(
        """SELECT bar_time, open_price, high_price, low_price, close_price, volume
           FROM daily_price_bars
           WHERE symbol = %s
           ORDER BY bar_time DESC LIMIT 260""",
        (symbol,),
    )
    complete = [row for row in bars if all(row.get(key) is not None for key in ("open_price", "high_price", "low_price", "close_price"))]
    if len(complete) < 20:
        return None
    metrics = analyze_bars(complete)
    review_date = complete[0]["bar_time"].date()
    options = _option_position(database, symbol)
    metrics["options"] = {key: value for key, value in options.items() if key != "rows"}

    unusual = []
    for row in options["rows"]:
        for side in ("call", "put"):
            volume = float(row[f"{side}_volume"] or 0)
            oi = float(row[f"{side}_open_interest"] or 0)
            if volume >= 1000 and (oi == 0 or volume / oi >= 0.5):
                unusual.append((volume, side, row, oi))
    for volume, side, row, oi in sorted(unusual, reverse=True, key=lambda item: item[0])[:3]:
        database.store_event(
            {
                "symbol": symbol, "event_time": datetime.now(timezone.utc).isoformat(),
                "event_type": "unusual_option", "severity": "high" if volume >= 10000 else "watch",
                "title": f"{side.upper()} 期权异动 · {row['strike']} · 成交 {volume:,.0f}",
                "details": {"side": side, "strike": float(row["strike"]), "volume": volume, "open_interest": oi, "expiration": str(row["expiration_date"]), "direction": "unknown"},
                "source": "Alpaca indicative options",
                "unique_key": f"alpaca-option:{symbol}:{review_date}:{side}:{row['expiration_date']}:{row['strike']}",
            }
        )

    option_text = "期权数据不足"
    if options.get("call_wall") is not None:
        ratio = options.get("put_call_ratio")
        option_text = f"近月Put墙 {_price(options['put_wall'])}、Call墙 {_price(options['call_wall'])}" + (f"，Put/Call持仓代理比 {ratio:.2f}" if ratio is not None else "")
    summary = (
        f"{metrics['bias']}（{metrics['score']:+.0f}分）。当日{_pct(metrics['day_change_pct'])}、量比{metrics['relative_volume']:.2f}，{metrics['tape']}；"
        f"20日资金流：{metrics['flow']}（CMF {metrics['cmf20']:+.2f}）。60日成交密集成本 {_price(metrics['poc_60d'])}，"
        f"价值区 {_price(metrics['value_area_low'])}–{_price(metrics['value_area_high'])}；{metrics['position']}。"
        f"最近支撑 {_price(metrics['support'])}、压力 {_price(metrics['resistance'])}，状态为“{metrics['breakout']}”，{metrics['support_test']}。{option_text}。"
    )
    review = {
        "symbol": symbol, "review_date": review_date, "close_price": metrics["close"],
        "short_trend": metrics["tape"], "medium_trend": metrics["flow"],
        "long_trend": metrics["position"], "support_price": metrics["support"],
        "resistance_price": metrics["resistance"], "breakout_status": metrics["breakout"],
        "large_trade_count": 0, "unusual_option_count": len(unusual),
        "score": metrics["score"], "summary": summary, "metrics": metrics,
    }
    database.store_review(review)
    return review


def main() -> None:
    database = Database()
    try:
        database.initialize()
        reviews = [
            review
            for symbol in database.active_symbols()
            if (review := generate_review(database, symbol))
        ]
    finally:
        database.close()
    print(json.dumps({"reviews": reviews}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
