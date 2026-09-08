from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from typing import Any

from .analytics import money_flow, rule_next_day_draft, volume_profile
from .calendar import is_trading_day
from .config import Settings
from .database import Database
from .impact import macro_impact, news_impacts
from .llm import (
    QUOTA_EXHAUSTED,
    RETRY_ON_REFRESH_STATUSES,
    complete_review,
    llm_status_message,
    reuse_llm_if_unchanged,
)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


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

    flow_data = money_flow(bars)
    cmf20 = flow_data.get("cmf20")
    obv_change = flow_data.get("obv_5d_normalized")
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

    profile = volume_profile(bars[:60], latest_first=True)
    def typical_vwap(sample: list[dict]) -> float | None:
        total_volume = sum(float(row.get("volume") or 0) for row in sample)
        return sum(((float(row["high_price"]) + float(row["low_price"]) + float(row["close_price"])) / 3) * float(row.get("volume") or 0) for row in sample) / total_volume if total_volume else None
    avwap20, avwap60 = typical_vwap(bars[:20]), typical_vwap(bars[:60])
    moving_average = lambda n: _mean([float(row["close_price"]) for row in bars[:n]]) if len(bars) >= n else None
    ma5, ma20, ma50, ma200 = moving_average(5), moving_average(20), moving_average(50), moving_average(200)

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
        "avwap20": avwap20, "avwap60": avwap60,
        "ma5": ma5, "ma20": ma20, "ma50": ma50, "ma200": ma200,
        "support": support, "resistance": resistance, "support_test": support_test,
        "support_levels": supports[:3], "resistance_levels": resistances[:3],
        "position": position, "score": score, "bias": bias,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def pack_review_context(
    symbol: str,
    review_date,
    metrics: dict,
    news: list[dict],
    macro: list[dict],
    segments: list[dict],
) -> dict[str, Any]:
    compact_news = []
    for article in news[:8]:
        compact_news.append(
            {
                "headline": article.get("headline"),
                "summary": (article.get("summary") or "")[:280],
                "themes": article.get("theme_names") or article.get("themes") or [],
                "impacts": [
                    {
                        "direction": item.get("direction"),
                        "theme_name": item.get("theme_name"),
                        "rationale": item.get("rationale"),
                    }
                    for item in (article.get("impacts") or [])
                ],
            }
        )
    compact_macro = [
        {
            "name": event.get("name"),
            "narrative": event.get("narrative"),
            "surprise": event.get("surprise"),
            "impacts": [
                {
                    "direction": item.get("direction"),
                    "theme_name": item.get("theme_name"),
                    "rationale": item.get("rationale"),
                }
                for item in (event.get("impacts") or [])
            ],
        }
        for event in macro
        if event
    ]
    largest_up = max(
        (float(row.get("change_pct") or 0) for row in segments),
        default=None,
    )
    largest_down = min(
        (float(row.get("change_pct") or 0) for row in segments),
        default=None,
    )
    return _json_safe(
        {
            "symbol": symbol,
            "review_date": str(review_date),
            "tape": {
                "close": metrics.get("close"),
                "day_change_pct": metrics.get("day_change_pct"),
                "relative_volume": metrics.get("relative_volume"),
                "breakout": metrics.get("breakout"),
                "tape": metrics.get("tape"),
                "support": metrics.get("support"),
                "resistance": metrics.get("resistance"),
                "support_test": metrics.get("support_test"),
                "ma5": metrics.get("ma5"),
                "ma20": metrics.get("ma20"),
                "ma50": metrics.get("ma50"),
                "ma200": metrics.get("ma200"),
                "score": metrics.get("score"),
                "bias": metrics.get("bias"),
            },
            "news": compact_news,
            "macro": compact_macro,
            "segments": {
                "count": len(segments),
                "largest_up_pct": largest_up,
                "largest_down_pct": largest_down,
            },
        }
    )


def generate_review(
    database: Database,
    symbol: str,
    llm_fn=None,
    *,
    force_llm: bool = False,
    settings: Settings | None = None,
) -> dict | None:
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
    draft = rule_next_day_draft(metrics)

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

    theme_map = database.theme_symbols()
    news_rows = database.news_on_date(symbol, str(review_date))
    for article in news_rows:
        article["impacts"] = news_impacts(article, theme_map)
    macro_rows = [
        mapped
        for event in database.macro_events_between(str(review_date), str(review_date))
        if (mapped := macro_impact(event, theme_map))
    ]
    segments = database.segments(symbol, str(review_date))
    context = pack_review_context(symbol, review_date, metrics, news_rows, macro_rows, segments)
    config = settings or Settings()
    existing = database.review_row(symbol, str(review_date))
    fingerprint, cached = reuse_llm_if_unchanged(
        context,
        existing,
        model=config.llm_model or None,
        force=force_llm,
    )
    if cached:
        llm_result = cached
    else:
        llm_result = llm_fn(context) if llm_fn else complete_review(context, config)
        llm_result = {
            **llm_result,
            "llm_cached": False,
            "llm_generated_at": (
                datetime.now(timezone.utc)
                if llm_result.get("llm_status") == "ok"
                else None
            ),
        }

    option_text = "期权数据不足"
    if options.get("call_wall") is not None:
        ratio = options.get("put_call_ratio")
        option_text = f"近月Put墙 {_price(options['put_wall'])}、Call墙 {_price(options['call_wall'])}" + (f"，Put/Call持仓代理比 {ratio:.2f}" if ratio is not None else "")
    rel = metrics["relative_volume"]
    cmf = metrics["cmf20"]
    rel_text = "—" if rel is None else f"{rel:.2f}"
    cmf_text = "—" if cmf is None else f"{cmf:+.2f}"
    summary = (
        f"{metrics['bias']}（{metrics['score']:+.0f}分）。当日{_pct(metrics['day_change_pct'])}、量比{rel_text}，{metrics['tape']}；"
        f"20日资金流：{metrics['flow']}（CMF {cmf_text}）。60日成交密集成本 {_price(metrics['poc_60d'])}，"
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
        "rule_bias": draft["rule_bias"],
        "watch_low": draft["watch_low"],
        "watch_high": draft["watch_high"],
        "context": context,
        "llm_why": llm_result.get("llm_why"),
        "llm_outlook": llm_result.get("llm_outlook"),
        "llm_bias": llm_result.get("llm_bias"),
        "llm_model": llm_result.get("llm_model"),
        "llm_status": llm_result.get("llm_status") or "missing_key",
        "llm_context_hash": fingerprint,
        "llm_generated_at": llm_result.get("llm_generated_at"),
        "llm_cached": bool(llm_result.get("llm_cached")),
        "llm_error": (
            None
            if (llm_result.get("llm_status") or "missing_key") == "ok"
            else llm_result.get("llm_error") or llm_status_message(llm_result.get("llm_status"))
        ),
    }
    database.store_review(review)
    if len(complete) >= 2:
        prior_date = complete[1]["bar_time"].date()
        broke_support = (
            metrics["breakout"] in {"放量有效跌破", "缩量跌破待确认"}
            or metrics["support_test"] == "收盘跌破最近支撑"
        )
        broke_resistance = metrics["breakout"] in {"放量有效突破", "缩量突破待确认"}
        database.fill_review_outcome(
            symbol,
            str(prior_date),
            {
                "outcome_return_pct": metrics["day_change_pct"],
                "outcome_volume_ratio": metrics["relative_volume"],
                "outcome_broke_support": broke_support,
                "broke_resistance": broke_resistance,
            },
        )
    return review


def retry_reviews_for_llm(
    database: Database,
    review_date: str | None = None,
    symbol: str | None = None,
    llm_fn=None,
) -> dict[str, Any]:
    date_value = review_date or database.latest_review_date()
    if not date_value:
        return {
            "date": None,
            "retried": [],
            "quota_exhausted": False,
            "ok": 0,
            "skipped": "no_review_date",
        }
    try:
        closed = not is_trading_day(date.fromisoformat(str(date_value)[:10]))
    except ValueError:
        closed = False
    if closed:
        return {
            "date": date_value,
            "retried": [],
            "quota_exhausted": False,
            "ok": 0,
            "skipped": "market_closed",
        }
    rows = database.reviews_by_date(date_value)
    if symbol:
        wanted = symbol.upper()
        rows = [row for row in rows if str(row.get("symbol") or "").upper() == wanted]
    targets = [
        row for row in rows if row.get("llm_status") in RETRY_ON_REFRESH_STATUSES
    ]
    retried: list[dict[str, Any]] = []
    for row in targets:
        review = generate_review(database, row["symbol"], llm_fn=llm_fn)
        if not review:
            continue
        retried.append(
            {
                "symbol": review["symbol"],
                "llm_status": review.get("llm_status"),
                "llm_error": review.get("llm_error"),
            }
        )
        if review.get("llm_status") == QUOTA_EXHAUSTED:
            break
    remaining = database.reviews_by_date(date_value)
    if symbol:
        remaining = [
            row for row in remaining if str(row.get("symbol") or "").upper() == symbol.upper()
        ]
    return {
        "date": date_value,
        "retried": retried,
        "quota_exhausted": any(
            row.get("llm_status") == QUOTA_EXHAUSTED for row in remaining
        ),
        "ok": sum(1 for row in remaining if row.get("llm_status") == "ok"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate daily reviews; call the LLM only when inputs change"
    )
    parser.add_argument("--symbols", nargs="*", help="Optional watchlist symbols")
    parser.add_argument(
        "--force-llm",
        action="store_true",
        help="Ignore cached model output and call the LLM again",
    )
    args = parser.parse_args()
    database = Database()
    reviews: list[dict] = []
    env_result: dict = {"status": "missing"}
    try:
        database.initialize()
        symbols = args.symbols or database.active_symbols()
        reviews = [
            review
            for symbol in symbols
            if (review := generate_review(database, symbol, force_llm=args.force_llm))
        ]
        from .environment_job import publish_environment_snapshots

        try:
            briefing = database.briefing()
            alerts = briefing.get("alerts") or []
            if alerts:
                database.append_severity_alerts(alerts)
            database.append_job_run(
                {
                    "job_name": "review",
                    "status": "success",
                    "item_counts": {"reviews": len(reviews)},
                }
            )
        except Exception as exc:
            print(
                json.dumps(
                    {"review_shell_error": str(exc)},
                    ensure_ascii=False,
                )
            )
        try:
            env_result = publish_environment_snapshots(database, symbols=symbols)
        except Exception as exc:
            env_result = {"status": "failed", "error": str(exc), "publishState": "missing"}
            print(
                json.dumps(
                    {"environment_publish_error": str(exc)},
                    ensure_ascii=False,
                )
            )
    finally:
        database.close()
    print(
        json.dumps(
            {
                "reviews": reviews,
                "llm_called": sum(1 for row in reviews if not row.get("llm_cached")),
                "llm_cached": sum(1 for row in reviews if row.get("llm_cached")),
                "environment": {
                    "status": env_result.get("status"),
                    "written": env_result.get("written"),
                    "errors": env_result.get("errors"),
                },
            },
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
