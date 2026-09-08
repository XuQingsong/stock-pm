from stock_pm.environment import (
    failed_snapshot,
    synthesize_symbol_environment,
)


def _full_inputs() -> dict:
    return {
        "as_of_date": "2026-09-04",
        "symbol": "NVDA",
        "watch": {"symbol": "NVDA", "themes": ["semis", "high_valuation_growth"], "sector": "半导体"},
        "thesis": {
            "return_1y_pct": 42.5,
            "earnings_year": {
                "quarters": 4,
                "eps_beats": 3,
                "eps_scored": 4,
                "eps_missing_estimate": 0,
                "revenue_beats": 2,
                "revenue_scored": 3,
                "revenue_missing_estimate": 1,
            },
            "growth": {
                "revenue_yoy_pct": 18.0,
                "phase": "仍高增",
                "peer_theme": "semis",
                "peer_revenue_yoy_median": 12.0,
                "vs_peers": "高于同主题中位",
            },
            "valuation": {
                "pe_current": 45.2,
                "pe_percentile": 78.0,
                "samples": 20,
                "label": "偏高",
                "basis": "用当前 TTM EPS 回推一年 PE 分位，不是当时实时 PE",
            },
        },
        "technical": {
            "return_1y_pct": 42.5,
            "return_20d_pct": -8.5,
            "return_5d_pct": -3.2,
            "distance_52w_high_pct": -12.0,
            "rsi14": 42,
            "volume_ratio_20d": 1.1,
            "health": "走坏",
        },
        "news": [
            {
                "symbol": "NVDA",
                "headline": "NVDA 与某云厂商扩大合作",
                "themes": ["semis"],
                "impacts": [
                    {
                        "theme": "semis",
                        "theme_name": "半导体/AI",
                        "direction": "利多",
                        "symbols": ["NVDA", "AVGO"],
                    }
                ],
            }
        ],
        "peer_news": [
            {
                "symbol": "AVGO",
                "headline": "存储缺货延续",
                "themes": ["semis"],
                "impacts": [
                    {
                        "theme": "semis",
                        "direction": "利多",
                        "symbols": ["MU", "NVDA"],
                    }
                ],
            }
        ],
        "impact": {
            "macro": [
                {
                    "name": "非农",
                    "narrative": "非农弱于预期 → 降息预期升温",
                    "row_thesis": "非农弱于预期 → 降息预期升温，因此利多高估值成长（NVDA）。",
                    "impacts": [
                        {
                            "theme": "high_valuation_growth",
                            "theme_name": "高估值成长",
                            "direction": "利多",
                            "symbols": ["NVDA", "AVGO"],
                        }
                    ],
                }
            ]
        },
        "briefing_row": {
            "symbol": "NVDA",
            "health": "走坏",
            "breakout_status": "放量有效跌破",
            "context": {
                "news": [
                    {
                        "headline": "芯片股获上调",
                        "impacts": [{"direction": "利多", "theme_name": "半导体/AI"}],
                    }
                ]
            },
        },
        "session": {"is_trading_day": True},
    }


def test_snapshot_answers_acceptance_environment_questions() -> None:
    env = synthesize_symbol_environment(**_full_inputs())
    assert env["scope"] == "symbol"
    assert env["symbol"] == "NVDA"
    assert env["publishState"] == "published"
    assert env["prediction_ready"] is False
    assert env["missingFlags"] == []
    struct = env["struct"]
    assert "过去一年约涨 42.5%" in struct["fundamentals"]["year_move"]["clause"]
    assert "EPS 超预期 3/4" in struct["fundamentals"]["earnings"]["clause"]
    assert "仍高增" in struct["fundamentals"]["industry"]["clause"]
    assert "偏高" in struct["fundamentals"]["valuation"]["clause"]
    assert struct["news"]["macro"]["bias"] == "利多"
    assert struct["news"]["sector"]["bias"] == "利多"
    assert struct["news"]["company"]["bias"] == "利多"
    assert struct["sentiment"]["atmosphere"] == "承压"
    assert "标题" in struct["sentiment"]["clause"]
    assert "42.5%" in env["synthesis"]
    assert env["conflict"] is True
    assert "不当成两套并列结论" in env["row_thesis"]
    assert env["one_liner"] == env["row_thesis"]


def test_empty_inputs_are_honest_missing() -> None:
    env = synthesize_symbol_environment(as_of_date="2026-09-08", symbol="INTC")
    assert env["publishState"] == "missing"
    for flag in (
        "fundamentals.year_move",
        "fundamentals.earnings",
        "fundamentals.industry",
        "fundamentals.valuation",
        "news.macro",
        "news.sector",
        "news.company",
        "sentiment",
    ):
        assert flag in env["missingFlags"]
    assert "暂缺" in env["synthesis"]
    assert env["struct"]["fundamentals"]["valuation"] is None
    assert env["struct"]["sentiment"] is None
    text = str(env)
    assert "PE " not in text
    assert "持续超预期" not in text


def test_earnings_without_estimates_do_not_claim_beats() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-04",
        symbol="INTC",
        thesis={
            "earnings_year": {
                "quarters": 4,
                "eps_beats": 0,
                "eps_scored": 0,
                "eps_missing_estimate": 4,
                "revenue_beats": 0,
                "revenue_scored": 0,
                "revenue_missing_estimate": 4,
            },
            "growth": {"phase": "样本不足"},
            "valuation": {"label": "数据不足", "pe_current": 12.0, "samples": 0},
        },
    )
    assert "fundamentals.earnings" in env["missingFlags"]
    assert "fundamentals.valuation" in env["missingFlags"]
    assert env["struct"]["fundamentals"]["earnings"] is None
    assert env["struct"]["fundamentals"]["valuation"] is None
    assert "持续超预期" not in env["synthesis"]
    assert "12.0" not in env["synthesis"]


def test_sentiment_uses_path_not_title_emotion() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-04",
        symbol="MU",
        watch={"themes": ["semis"]},
        technical={
            "return_20d_pct": -16.0,
            "return_5d_pct": -9.0,
            "distance_52w_high_pct": -30.0,
            "health": "走坏",
        },
        news=[
            {
                "symbol": "MU",
                "headline": "Profits surge to record high",
                "sentiment": "positive",
                "themes": ["semis"],
                "impacts": [
                    {"theme": "semis", "direction": "利多", "symbols": ["MU"]}
                ],
            }
        ],
    )
    assert env["struct"]["sentiment"]["atmosphere"] == "恐慌"
    assert env["struct"]["sentiment"]["method"] == "path"
    assert "偏多" not in (env["struct"]["sentiment"]["clause"] or "")
    assert env["struct"]["news"]["company"]["bias"] == "利多"


def test_unmapped_news_does_not_invent_bias() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-04",
        symbol="AAPL",
        watch={"themes": ["consumer_electronics"]},
        news=[
            {
                "symbol": "AAPL",
                "headline": "Random blog post",
                "themes": ["consumer_electronics"],
                "impacts": [],
            }
        ],
    )
    assert "news.company" in env["missingFlags"]
    assert env["struct"]["news"]["company"]["bias"] is None
    assert "不编方向" in env["struct"]["news"]["company"]["clause"]


def test_failed_snapshot_has_no_fabricated_numbers() -> None:
    snap = failed_snapshot("NVDA", "2026-09-04", "thesis exploded")
    assert snap["publishState"] == "missing"
    assert snap["struct"]["fundamentals"] is None
    assert snap["struct"]["sentiment"] is None
    assert "未编造数字" in snap["one_liner"]
    assert not any(isinstance(value, (int, float)) for value in snap["struct"].values())


def test_holiday_publish_state_is_stale() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-07",
        symbol="AAPL",
        thesis={"return_1y_pct": 10.0},
        technical={"return_1y_pct": 10.0, "return_20d_pct": 1.0, "health": "观察"},
        session={"is_trading_day": False, "label": "劳动节，美股休市"},
    )
    assert env["publishState"] == "stale"
    assert "不编造当日盘面" in env["one_liner"]
