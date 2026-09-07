from __future__ import annotations


def sentiment_from_components(
    news: dict,
    options: dict,
    prices: list[dict],
) -> dict:
    news_total = int(news["total"] or 0)
    news_score = None
    if news_total:
        news_score = 100 * (int(news["positive"]) - int(news["negative"])) / news_total

    call_oi = float(options["call_oi"] or 0)
    put_oi = float(options["put_oi"] or 0)
    put_call_oi_ratio = put_oi / call_oi if call_oi else None
    option_score = None
    if put_call_oi_ratio is not None:
        option_score = 100 * (1 - put_call_oi_ratio) / (1 + put_call_oi_ratio)

    momentum_20d_pct = None
    momentum_score = None
    if len(prices) >= 21 and prices[20]["close_price"]:
        momentum_20d_pct = 100 * (
            float(prices[0]["close_price"]) / float(prices[20]["close_price"]) - 1
        )
        momentum_score = max(-100, min(100, momentum_20d_pct * 3))

    components = [
        (news_score, 0.45),
        (option_score, 0.30),
        (momentum_score, 0.25),
    ]
    available = [(value, weight) for value, weight in components if value is not None]
    weight_total = sum(weight for _, weight in available)
    composite = (
        sum(value * weight for value, weight in available) / weight_total
        if weight_total
        else None
    )
    label = "数据不足"
    if composite is not None:
        label = "偏多" if composite >= 25 else "偏空" if composite <= -25 else "中性"

    call_volume = float(options["call_volume"] or 0)
    put_volume = float(options["put_volume"] or 0)
    return {
        "score": round(composite, 1) if composite is not None else None,
        "label": label,
        "news_score": round(news_score, 1) if news_score is not None else None,
        "news_positive": int(news["positive"] or 0),
        "news_neutral": int(news["neutral"] or 0),
        "news_negative": int(news["negative"] or 0),
        "news_total": news_total,
        "put_call_oi_ratio": round(put_call_oi_ratio, 2) if put_call_oi_ratio is not None else None,
        "put_call_volume_ratio": round(put_volume / call_volume, 2) if call_volume else None,
        "momentum_20d_pct": round(momentum_20d_pct, 2) if momentum_20d_pct is not None else None,
        "method": "新闻45% + 期权30% + 20日动量25%；缺失项按可用权重归一化",
    }
