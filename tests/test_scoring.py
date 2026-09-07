from stock_pm.scoring import sentiment_from_components


def test_sentiment_normalizes_available_components() -> None:
    result = sentiment_from_components(
        {"total": 10, "positive": 7, "neutral": 2, "negative": 1},
        {"call_oi": 100, "put_oi": 50, "call_volume": 20, "put_volume": 10},
        [{"close_price": 110}] * 10 + [{"close_price": 100}] * 11,
    )
    assert result["label"] == "偏多"
    assert result["news_score"] == 60.0
    assert result["put_call_oi_ratio"] == 0.5
    assert result["momentum_20d_pct"] == 10.0
