from stock_pm.impact import macro_impact, news_sentiment, tag_news


def test_tag_news_detects_rates_theme() -> None:
    themes = tag_news("Fed signals rate cut as inflation cools")
    assert "rates" in themes


def test_tag_news_detects_semis_and_stays_empty_when_unknown() -> None:
    assert "semis" in tag_news("Nvidia unveils new GPU for data center AI")
    assert tag_news("Local bakery wins award") == []


def test_news_sentiment_direction() -> None:
    assert news_sentiment("Profits surge to record high") == "positive"
    assert news_sentiment("Company misses estimates, shares drop") == "negative"


def test_macro_impact_maps_weak_nfp_to_growth_and_gold() -> None:
    event = {
        "event_type": "nfp",
        "event_time": "2026-09-04T12:30:00+00:00",
        "name": "非农",
        "actual": 142,
        "consensus": 160,
        "unit": "千人",
        "surprise": "below",
    }
    result = macro_impact(event, {"high_valuation_growth": ["NVDA", "QQQ"], "gold": []})
    assert result is not None
    assert "降息预期" in result["narrative"]
    themes = {impact["theme"]: impact for impact in result["impacts"]}
    assert themes["high_valuation_growth"]["direction"] == "利多"
    assert themes["high_valuation_growth"]["symbols"] == ["NVDA", "QQQ"]


def test_macro_impact_returns_none_without_rule() -> None:
    event = {"event_type": "gdp", "surprise": "above", "event_time": "", "name": "GDP"}
    assert macro_impact(event, {}) is None
