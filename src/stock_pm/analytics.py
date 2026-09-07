from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import floor
from statistics import median
from typing import Any


INTRADAY_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "60m": 60}
SUPPORTED_INTERVALS = {*INTRADAY_MINUTES, "1d", "1w", "1M"}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resample_bars(bars: list[dict], interval: str) -> list[dict]:
    """Aggregate chronological OHLCV bars to the requested interval."""
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    if interval in {"1m", "1d"}:
        return [dict(row) for row in bars]

    grouped: dict[Any, list[dict]] = defaultdict(list)
    for row in bars:
        stamp = row["bar_time"]
        if not isinstance(stamp, datetime):
            stamp = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if interval in INTRADAY_MINUTES:
            minutes = INTRADAY_MINUTES[interval]
            stamp = stamp.replace(
                minute=floor(stamp.minute / minutes) * minutes,
                second=0,
                microsecond=0,
            )
            key = stamp
        elif interval == "1w":
            key = stamp.date().toordinal() - stamp.weekday()
        else:
            key = (stamp.year, stamp.month)
        grouped[key].append(row)

    result = []
    for rows in grouped.values():
        rows.sort(key=lambda item: item["bar_time"])
        result.append(
            {
                "symbol": rows[0].get("symbol"),
                "bar_time": rows[0]["bar_time"],
                "open_price": rows[0]["open_price"],
                "high_price": max(
                    float(row["high_price"]) for row in rows if row.get("high_price") is not None
                ),
                "low_price": min(
                    float(row["low_price"]) for row in rows if row.get("low_price") is not None
                ),
                "close_price": rows[-1]["close_price"],
                "volume": sum(float(row.get("volume") or 0) for row in rows),
                "source": rows[-1].get("source"),
            }
        )
    return sorted(result, key=lambda item: item["bar_time"])


CHART_MA_PERIODS = (5, 20, 50, 200)
VALID_BIASES = ("偏多", "中性", "偏空")


def enrich_chart_bars(bars: list[dict]) -> list[dict]:
    """Add amount, MA5/20/50/200 and KDJ(9,3,3) to chronological bars."""
    result: list[dict] = []
    closes: list[float] = []
    k_value = d_value = 50.0
    for index, row in enumerate(bars):
        close = float(row["close_price"])
        high = float(row["high_price"])
        low = float(row["low_price"])
        volume = float(row.get("volume") or 0)
        closes.append(close)
        window = bars[max(0, index - 8) : index + 1]
        highest = max(float(item["high_price"]) for item in window)
        lowest = min(float(item["low_price"]) for item in window)
        rsv = 50.0 if highest == lowest else 100 * (close - lowest) / (highest - lowest)
        k_value = (2 * k_value + rsv) / 3
        d_value = (2 * d_value + k_value) / 3
        enriched = {
            **row,
            "amount": round(((high + low + close) / 3) * volume, 2),
            "k": round(k_value, 3),
            "d": round(d_value, 3),
            "j": round(3 * k_value - 2 * d_value, 3),
        }
        for periods in CHART_MA_PERIODS:
            values = closes[-periods:]
            enriched[f"ma{periods}"] = (
                round(sum(values) / periods, 4) if len(values) == periods else None
            )
        result.append(enriched)
    return result


def volume_profile(
    bars: list[dict], bins: int = 32, latest_first: bool = False
) -> dict[str, Any]:
    """Approximate volume-at-price by spreading each OHLCV bar over its range."""
    if latest_first:
        bars = list(reversed(bars))
    valid = [
        row
        for row in bars
        if all(_number(row.get(key)) is not None for key in ("high_price", "low_price", "close_price"))
        and (_number(row.get("volume")) or 0) > 0
    ]
    if not valid:
        return {
            "buckets": [],
            "poc": None,
            "value_low": None,
            "value_high": None,
            "volume_below_pct": None,
            "current_price": None,
            "support_levels": [],
            "resistance_levels": [],
        }
    minimum = min(float(row["low_price"]) for row in valid)
    maximum = max(float(row["high_price"]) for row in valid)
    current = float(valid[-1]["close_price"])
    if maximum <= minimum:
        return {
            "buckets": [{"price": current, "volume": sum(float(r["volume"]) for r in valid), "volume_pct": 100.0}],
            "poc": current,
            "value_low": current,
            "value_high": current,
            "volume_below_pct": 100.0,
            "current_price": current,
            "support_levels": [],
            "resistance_levels": [],
        }

    width = (maximum - minimum) / bins
    bucket_volume = [0.0] * bins
    for row in valid:
        low = float(row["low_price"])
        high = float(row["high_price"])
        volume = float(row["volume"])
        first = max(0, min(bins - 1, int((low - minimum) / width)))
        last = max(0, min(bins - 1, int((high - minimum) / width)))
        count = last - first + 1
        for index in range(first, last + 1):
            bucket_volume[index] += volume / count

    total = sum(bucket_volume)
    poc_index = max(range(bins), key=bucket_volume.__getitem__)
    left = right = poc_index
    selected = bucket_volume[poc_index]
    while selected < total * 0.70 and (left > 0 or right < bins - 1):
        left_value = bucket_volume[left - 1] if left > 0 else -1
        right_value = bucket_volume[right + 1] if right < bins - 1 else -1
        if right_value >= left_value:
            right += 1
            selected += bucket_volume[right]
        else:
            left -= 1
            selected += bucket_volume[left]

    buckets = [
        {
            "price": round(minimum + (index + 0.5) * width, 4),
            "volume": round(value, 2),
            "volume_pct": round(100 * value / total, 2) if total else 0,
        }
        for index, value in enumerate(bucket_volume)
    ]
    ranked = sorted(range(bins), key=bucket_volume.__getitem__, reverse=True)
    supports = [
        buckets[index]["price"] for index in ranked if buckets[index]["price"] < current
    ][:3]
    resistances = [
        buckets[index]["price"] for index in ranked if buckets[index]["price"] > current
    ][:3]
    below = sum(
        item["volume"] for item in buckets if item["price"] <= current
    )
    return {
        "buckets": buckets,
        "poc": buckets[poc_index]["price"],
        "value_low": round(minimum + left * width, 4),
        "value_high": round(minimum + (right + 1) * width, 4),
        "volume_below_pct": round(100 * below / total, 2) if total else None,
        "current_price": current,
        "support_levels": sorted(supports, reverse=True),
        "resistance_levels": sorted(resistances),
    }


def money_flow(bars_latest_first: list[dict], periods: int = 20) -> dict[str, Any]:
    sample = bars_latest_first[:periods]
    mfv = total_volume = 0.0
    for row in sample:
        high, low, close, volume = (
            float(row.get(key) or 0)
            for key in ("high_price", "low_price", "close_price", "volume")
        )
        if high > low and volume > 0:
            mfv += ((2 * close - high - low) / (high - low)) * volume
            total_volume += volume
    cmf = mfv / total_volume if total_volume else None
    chronological = list(reversed(bars_latest_first[:30]))
    obv = [0.0]
    for prior, current in zip(chronological, chronological[1:]):
        direction = (
            1
            if current["close_price"] > prior["close_price"]
            else -1
            if current["close_price"] < prior["close_price"]
            else 0
        )
        obv.append(obv[-1] + direction * float(current.get("volume") or 0))
    recent = sum(float(row.get("volume") or 0) for row in bars_latest_first[:5])
    obv_change = (
        (obv[-1] - obv[-6]) / recent if len(obv) >= 6 and recent else None
    )
    if cmf is not None and cmf >= 0.10 and (obv_change or 0) > 0:
        label = "吸筹代理信号"
    elif cmf is not None and cmf <= -0.10 and (obv_change or 0) < 0:
        label = "派发代理信号"
    elif (cmf or 0) > 0:
        label = "资金流代理略偏正"
    elif (cmf or 0) < 0:
        label = "资金流代理略偏负"
    else:
        label = "资金流代理中性"
    return {
        "cmf20": round(cmf, 4) if cmf is not None else None,
        "obv_5d_normalized": round(obv_change, 4) if obv_change is not None else None,
        "flow_label": label,
    }


def percentile(values: list[float], value: float) -> float | None:
    if not values:
        return None
    return round(100 * sum(item <= value for item in values) / len(values), 1)


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def earnings_summary(rows: list[dict]) -> dict[str, Any]:
    latest = rows[0] if rows else None
    highlights: list[str] = []
    if latest:
        for label, actual_key, estimate_key, surprise_key in (
            ("EPS", "eps_actual", "eps_estimate", "eps_surprise_pct"),
            ("营收", "revenue_actual", "revenue_estimate", "revenue_surprise_pct"),
            ("净利润", "net_income_actual", "net_income_estimate", "net_income_surprise_pct"),
        ):
            actual = _number(latest.get(actual_key))
            estimate = _number(latest.get(estimate_key))
            surprise = _number(latest.get(surprise_key))
            if actual is not None and estimate is not None:
                direction = "高于" if actual >= estimate else "低于"
                suffix = f"（{surprise:+.1f}%）" if surprise is not None else ""
                highlights.append(f"{label}实际值{direction}市场预期{suffix}")
        move = _number(latest.get("post_1d_return_pct"))
        if move is not None:
            highlights.append(f"财报后首个交易日股价反应为 {move:+.2f}%")
    if not highlights:
        highlights.append("当前供应商只提供有限财报字段，缺失项未作估算")
    moves = [
        abs(value)
        for row in rows
        if (value := _number(row.get("post_1d_return_pct"))) is not None
    ]
    return {
        "latest": latest,
        "history": rows,
        "highlights": highlights[:3],
        "avg_abs_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
    }


def return_1y_pct(bars_latest_first: list[dict]) -> float | None:
    if len(bars_latest_first) < 2:
        return None
    latest = _number(bars_latest_first[0].get("close_price"))
    older = _number(bars_latest_first[min(251, len(bars_latest_first) - 1)].get("close_price"))
    if not latest or not older:
        return None
    return round(100 * (latest / older - 1), 2)


def earnings_scorecard(rows: list[dict], limit: int = 4) -> dict[str, Any]:
    sample = rows[:limit]
    def _beats(actual_key: str, estimate_key: str) -> tuple[int, int, int]:
        scored = 0
        beats = 0
        missing = 0
        for row in sample:
            actual = _number(row.get(actual_key))
            estimate = _number(row.get(estimate_key))
            if actual is None:
                continue
            if estimate is None:
                missing += 1
                continue
            scored += 1
            if actual >= estimate:
                beats += 1
        return beats, scored, missing

    eps_beats, eps_scored, eps_missing = _beats("eps_actual", "eps_estimate")
    rev_beats, rev_scored, rev_missing = _beats("revenue_actual", "revenue_estimate")
    latest = sample[0] if sample else None
    return {
        "quarters": len(sample),
        "eps_beats": eps_beats,
        "eps_scored": eps_scored,
        "eps_missing_estimate": eps_missing,
        "revenue_beats": rev_beats,
        "revenue_scored": rev_scored,
        "revenue_missing_estimate": rev_missing,
        "latest_eps_surprise_pct": _number((latest or {}).get("eps_surprise_pct")),
        "latest_revenue_surprise_pct": _number((latest or {}).get("revenue_surprise_pct")),
    }


def yoy_from_rows(rows: list[dict], field: str) -> float | None:
    latest = next((row for row in rows if _number(row.get(field)) is not None), None)
    if latest is None:
        return None
    now = _number(latest.get(field))
    year = latest.get("fiscal_year")
    period = latest.get("fiscal_period")
    prior = None
    if year and period:
        prior = next(
            (
                row
                for row in rows
                if row.get("fiscal_year") == year - 1
                and row.get("fiscal_period") == period
                and _number(row.get(field)) is not None
            ),
            None,
        )
    if prior is None and len(rows) >= 5:
        prior = rows[4] if _number(rows[4].get(field)) is not None else None
    old = _number((prior or {}).get(field)) if prior else None
    if now is None or not old:
        return None
    return round(100 * (now / old - 1), 2)


def growth_phase_label(yoy: float | None, prior_yoy: float | None = None) -> str:
    if yoy is None:
        return "样本不足"
    if yoy < 0:
        return "转负"
    if prior_yoy is not None and yoy >= prior_yoy + 3:
        return "加速"
    if prior_yoy is not None and yoy <= prior_yoy - 3:
        return "放缓"
    if yoy >= 15:
        return "仍高增"
    return "放缓"


def reconstructed_pe_view(
    closes_latest_first: list[float],
    eps_ttm: float | None,
    pe_ttm: float | None,
) -> dict[str, Any]:
    if not eps_ttm or eps_ttm == 0 or not closes_latest_first:
        return {
            "pe_current": pe_ttm,
            "pe_percentile": None,
            "pe_low": None,
            "pe_high": None,
            "samples": 0,
            "label": "数据不足",
            "basis": "用当前 TTM EPS 回推一年 PE 分位，不是当时实时 PE",
        }
    series = [close / eps_ttm for close in closes_latest_first if close]
    current = pe_ttm if pe_ttm is not None else (series[0] if series else None)
    enough = len(series) >= 8
    pct = percentile(series, current) if current is not None and series else None
    if pct is None:
        label = "数据不足"
    elif pct < 30:
        label = "偏低"
    elif pct > 70:
        label = "偏高"
    else:
        label = "中性"
    return {
        "pe_current": round(current, 2) if current is not None else None,
        "pe_percentile": pct,
        "pe_low": quantile(series, 0.1) if enough else None,
        "pe_high": quantile(series, 0.9) if enough else None,
        "samples": len(series),
        "label": label,
        "basis": "用当前 TTM EPS 回推一年 PE 分位，不是当时实时 PE",
    }


def tape_health(technical: dict, review: dict | None = None) -> str:
    review = review or {}
    rsi = _number(technical.get("rsi14"))
    volume_ratio = _number(technical.get("volume_ratio_20d")) or _number(
        (review.get("metrics") or {}).get("relative_volume")
    )
    breakout = review.get("breakout_status") or ""
    support_test = review.get("support_test") or (review.get("metrics") or {}).get("support_test")
    if breakout == "放量有效跌破" or support_test == "收盘跌破最近支撑":
        return "走坏"
    if rsi is not None and rsi >= 75:
        return "过热"
    if volume_ratio is not None and volume_ratio < 0.75:
        return "缩量无方向"
    close = _number(technical.get("close_price"))
    ma50 = _number(technical.get("ma50"))
    if technical.get("bullish_alignment") or (close and ma50 and close > ma50):
        return "趋势健康"
    return "观察"


def ma_position_text(technical: dict) -> str:
    parts = []
    close = _number(technical.get("close_price"))
    for key, label in (("ma20", "MA20"), ("ma50", "MA50"), ("ma200", "MA200")):
        value = _number(technical.get(key))
        if close is None or value is None:
            parts.append(f"{label}不足")
            continue
        side = "上方" if close >= value else "下方"
        parts.append(f"{label}{side}")
    return " · ".join(parts) if parts else "均线不足"


def rule_next_day_draft(metrics: dict) -> dict[str, Any]:
    score = _number(metrics.get("score")) or 0
    breakout = metrics.get("breakout") or ""
    if breakout == "放量有效突破" or score >= 25:
        bias = "偏多"
    elif breakout == "放量有效跌破" or score <= -25:
        bias = "偏空"
    else:
        bias = "中性"
    return {
        "rule_bias": bias,
        "watch_low": metrics.get("support"),
        "watch_high": metrics.get("resistance"),
    }


def pick_outlook_bias(review: dict) -> tuple[str | None, str]:
    if review.get("user_bias") in VALID_BIASES or review.get("user_bias") == "观望":
        return review["user_bias"], "user"
    if review.get("llm_bias") in VALID_BIASES:
        return review["llm_bias"], "llm"
    if review.get("rule_bias") in VALID_BIASES:
        return review["rule_bias"], "rule"
    return None, "none"


def judge_outcome(
    bias: str | None,
    day_change_pct: float | None,
    broke_support: bool,
    broke_resistance: bool = False,
) -> str:
    change = day_change_pct or 0
    if bias in (None, "观望", "中性"):
        if abs(change) < 1 and not broke_support and not broke_resistance:
            return "符合"
        if abs(change) >= 2 or broke_support or broke_resistance:
            return "相反"
        return "含糊"
    if bias == "偏多":
        if change > 0.3 and not broke_support:
            return "符合"
        if change < -0.3 or broke_support:
            return "相反"
        return "含糊"
    if bias == "偏空":
        if change < -0.3 and not broke_resistance:
            return "符合"
        if change > 0.3 or broke_resistance:
            return "相反"
        return "含糊"
    return "含糊"
