import inspect
import re

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.environment import (
    SYMBOL_FIELD_FLAGS,
    failed_snapshot,
    is_causal_chain,
    synthesize_symbol_environment,
)
from stock_pm.errors import DatabaseError
from stock_pm.queries import QueryMixin

_UNTYPED_IS_NULL = re.compile(
    r"%s(?!::)\s+IS\s+NULL",
    re.IGNORECASE,
)


class _TypedSnapshotHarness(QueryMixin):
    """Runs the real symbol-scoped snapshot SQL path without a live database.

    PostgreSQL cannot infer a type for a bare ``%s IS NULL`` bind (production
    503: could not determine data type of parameter $3). This harness rejects
    that shape so the regression fails if the cast is reverted.
    """

    def fetch_all(self, query, params=()):
        if _UNTYPED_IS_NULL.search(query):
            raise DatabaseError(
                "PostgreSQL query failed: could not determine data type of parameter $3"
            )
        return []

    def market_session(self, trade_date=None):
        return {
            "date": trade_date or "2026-09-04",
            "default_review_date": "2026-09-04",
            "is_trading_day": True,
        }

    def build_live_environment(self, symbol, as_of_date=None, **kwargs):
        return failed_snapshot(symbol, as_of_date, "no stored snapshot")


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
    line = env["one_liner"]
    assert line.index("盘面") < line.index("消息") < line.index("因此")
    assert "方向相反" in env["row_thesis"]
    assert "先以收盘盘面为准" in env["row_thesis"]
    assert env["one_liner"] == env["row_thesis"] == env["synthesis"]
    assert is_causal_chain(line)
    assert "可能相关" not in line
    assert all(item.get("points_to") == "A" for item in struct["bullets"])
    covered = set(env["missingFlags"])
    for flag in SYMBOL_FIELD_FLAGS:
        path = flag.split(".")
        node = struct
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        assert flag in covered or node is not None


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
    assert "不足" in env["synthesis"]
    assert "置信度有限" in env["synthesis"]
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
    assert "暂未形成对该股的明确影响" in env["struct"]["news"]["company"]["clause"]
    assert "不编方向" not in env["struct"]["news"]["company"]["clause"]


def test_causal_chain_rejects_slogan_halves() -> None:
    from stock_pm.environment import causal_one_liner, is_causal_chain

    good = causal_one_liner("走坏，放量有效跌破", "偏多（芯片股获上调）", "bear", "bull")
    assert is_causal_chain(good)
    assert "先以收盘盘面为准" in good
    assert good.count("因此") == 1
    stripped = causal_one_liner(
        "走坏",
        "非农弱于预期 → 降息预期升温，因此利多高估值成长（NVDA）。",
        "bear",
        "bull",
    )
    assert is_causal_chain(stripped)
    assert stripped.count("因此") == 1
    assert "。" not in stripped.split("因此")[0]
    assert not is_causal_chain("走坏。可能相关：芯片股获上调。")
    assert not is_causal_chain("期权认沽偏多；自选趋势健康；宏观降息。")
    assert not is_causal_chain("盘面走坏。消息却偏多。两套并列。")


def test_failed_snapshot_has_no_fabricated_numbers() -> None:
    snap = failed_snapshot("NVDA", "2026-09-04", "thesis exploded")
    assert snap["publishState"] == "missing"
    assert snap["struct"]["fundamentals"] is None
    assert snap["struct"]["sentiment"] is None
    assert "当前判断置信度有限" in snap["one_liner"]
    assert "未编造" not in snap["one_liner"]
    assert snap["struct"]["news"] == {"macro": None, "sector": None, "company": None}
    dumped = str(snap["struct"])
    assert "return_1y" not in dumped
    assert "pe_current" not in dumped


def test_aligned_tape_and_news_still_not_a_prediction() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-04",
        symbol="AVGO",
        watch={"themes": ["semis"]},
        technical={"health": "趋势健康", "return_20d_pct": 6.0},
        news=[
            {
                "symbol": "AVGO",
                "headline": "行业缺货延续",
                "themes": ["semis"],
                "impacts": [{"theme": "semis", "direction": "利多", "symbols": ["AVGO"]}],
            }
        ],
        briefing_row={"symbol": "AVGO", "health": "趋势健康"},
    )
    line = env["one_liner"]
    assert line.index("盘面") < line.index("消息") < line.index("因此")
    assert is_causal_chain(line)
    assert "同向" in line
    assert "背景信息" in line
    assert "不写成预测" not in line
    assert env["prediction_ready"] is False
    assert env["conflict"] is False


def test_holiday_publish_state_is_stale() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-07",
        symbol="AAPL",
        thesis={"return_1y_pct": 10.0},
        technical={"return_1y_pct": 10.0, "return_20d_pct": 1.0, "health": "观察"},
        session={"is_trading_day": False, "label": "劳动节，美股休市"},
    )
    assert env["publishState"] == "stale"
    assert "沿用最近交易日环境作为背景" in env["one_liner"]
    assert "不编造" not in env["one_liner"]


def test_latest_environment_snapshot_sql_casts_nullable_symbol() -> None:
    source = inspect.getsource(QueryMixin.latest_environment_snapshot)
    assert "%s::text IS NULL" in source
    assert "symbol = %s::text" in source
    assert _UNTYPED_IS_NULL.search(source) is None


def test_latest_environment_snapshot_typed_binds_do_not_raise() -> None:
    harness = _TypedSnapshotHarness()
    assert harness.latest_environment_snapshot("2026-09-04", "symbol", "AAPL") is None
    assert harness.latest_environment_snapshot("2026-09-04", "market", None) is None


def test_get_environment_symbol_is_not_503(monkeypatch) -> None:
    monkeypatch.setattr(api, "database", _TypedSnapshotHarness())
    response = TestClient(api.app).get("/api/environment?symbol=AAPL")
    assert response.status_code != 503
    assert response.status_code == 200
    body = response.json()
    assert "could not determine data type" not in str(body).lower()
    assert body["symbol"] == "AAPL"
    assert body["scope"] == "symbol"
    assert body["publishState"] in {"published", "draft", "stale", "missing"}
