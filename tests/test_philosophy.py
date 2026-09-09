from datetime import datetime, timezone

from stock_pm.environment import is_causal_chain
from stock_pm.philosophy import (
    build_shell,
    derive_explicit_state,
    derive_severity_alerts,
    enrich_briefing_row,
    impact_row_thesis,
    pick_explicit_state,
    quote_quality,
    stock_row_thesis,
    synthesize_environment,
)


def test_quote_quality_prefers_review_then_prior_close() -> None:
    snap = {
        "last_price": 120,
        "prior_close": 100,
        "source": "alpaca_iex",
        "delayed": "1",
        "captured_at": "2026-09-08T12:00:00+00:00",
    }
    quality = quote_quality(snap, {"close_price": 101}, now=datetime(2026, 9, 8, 13, tzinfo=timezone.utc))
    assert quality["status"] == "delayed"
    assert quality["conclusion_price"] == 101
    assert quality["conclusion_source"] == "review_close"
    assert quality["usable_for_conclusion"] is True

    quality = quote_quality(snap, {}, now=datetime(2026, 9, 8, 13, tzinfo=timezone.utc))
    assert quality["conclusion_price"] == 100
    assert quality["conclusion_source"] == "prior_close"


def test_bad_quote_hides_last_price() -> None:
    quality = quote_quality({"last_price": 500, "prior_close": 100, "source": "alpaca_iex"})
    assert quality["status"] == "bad"
    assert quality["hide_last_price"] is True
    assert quality["last_price"] is None
    assert quality["conclusion_price"] == 100
    assert quality["usable_for_conclusion"] is True


def test_missing_quote() -> None:
    quality = quote_quality({})
    assert quality["status"] == "missing"
    assert quality["conclusion_source"] == "missing"
    assert quality["hide_last_price"] is True


def test_explicit_state_priority() -> None:
    assert pick_explicit_state(["missing", "face_slap", "overdue"]) == "face_slap"
    assert pick_explicit_state(["missing", "overdue"]) == "overdue"
    assert pick_explicit_state([]) == "clear"


def test_face_slap_shell_does_not_claim_prediction() -> None:
    briefing = {
        "date": "2026-09-08",
        "has_reviews": True,
        "session": {"is_trading_day": True},
        "rows": [
            {
                "symbol": "NVDA",
                "health": "走坏",
                "prior_outcome": {"outcome_vs_bias": "相反", "bias": "偏多"},
            }
        ],
    }
    env = synthesize_environment(as_of_date="2026-09-08", briefing_rows=briefing["rows"])
    state = derive_explicit_state(briefing=briefing, environment=env)
    assert state["code"] == "face_slap"
    assert state["prediction_ready"] is False
    alerts = derive_severity_alerts(briefing=briefing, explicit_state=state)
    assert alerts and alerts[0]["severity"] == "severe"
    assert "规则对照" in state["detail"]
    assert "不是时间窗口或涨跌边界" in state["detail"]
    assert alerts[0].get("cta") is None


def test_real_prediction_face_slap_is_ready_and_has_cta() -> None:
    pred = {
        "symbol": "INTC",
        "state": "invalidated",
        "prediction_ready": True,
        "window_start": "2026-09-08",
        "window_end": "2026-09-21",
        "window_label": "两周内",
        "upside_bound_pct": 10.0,
        "downside_bound_pct": -5.0,
        "badge": "两周内 上10% / 下5% · 已打脸",
    }
    briefing = {
        "date": "2026-09-09",
        "has_reviews": True,
        "session": {"is_trading_day": True},
        "rows": [{"symbol": "INTC", "prediction": pred}],
    }
    state = derive_explicit_state(briefing=briefing, environment={"publishState": "published"}, predictions=[pred])
    assert state["code"] == "face_slap"
    assert state["prediction_ready"] is True
    assert "改口" in state["detail"]
    alerts = derive_severity_alerts(briefing=briefing, explicit_state=state)
    assert alerts[0]["cta"] == "judgment_change"
    assert alerts[0].get("legacy") is False


def test_environment_missing_flags_are_honest() -> None:
    env = synthesize_environment(as_of_date="2026-09-08", options={"status": "missing"})
    assert env["publishState"] == "missing"
    assert "options" in env["missingFlags"]
    assert "macro" in env["missingFlags"]
    assert "reviews" in env["missingFlags"]
    assert env["prediction_ready"] is False
    assert "暂缺" in env["one_liner"]


def test_environment_one_liner_joins_facts() -> None:
    env = synthesize_environment(
        as_of_date="2026-09-04",
        briefing_rows=[{"symbol": "NVDA", "health": "趋势健康"}],
        options={"status": "ok", "total_put_call": 1.2, "trade_date": "2026-09-04"},
        impact={
            "macro": [
                {
                    "name": "非农",
                    "narrative": "非农弱于预期 → 降息预期升温",
                    "impacts": [
                        {
                            "direction": "利多",
                            "theme_name": "高估值成长",
                            "symbols": ["NVDA", "AVGO"],
                        }
                    ],
                }
            ]
        },
    )
    assert env["publishState"] == "published"
    assert env["missingFlags"] == []
    line = env["one_liner"]
    assert is_causal_chain(line)
    assert "趋势健康" in line
    assert "降息预期升温" in line
    assert "认沽偏多" in (env["struct"]["options"] or {}).get("clause", "")
    assert not line.startswith("期权")


def test_conflict_row_is_one_sentence() -> None:
    thesis = stock_row_thesis(
        {
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
        }
    )
    assert is_causal_chain(thesis)
    assert "不当成两套并列结论" in thesis
    assert "可点新闻" in thesis or "偏多" in thesis
    assert "可能相关" not in thesis
    assert thesis.find("。") > thesis.find("因此")
    mapped = impact_row_thesis(
        {
            "narrative": "非农弱于预期 → 降息预期升温",
            "impacts": [
                {"direction": "利多", "theme_name": "高估值成长", "symbols": ["NVDA"]}
            ],
        }
    )
    assert mapped.startswith("非农弱于预期")
    assert "利多高估值成长（NVDA）" in mapped
    assert mapped.count("。") == 1


def test_enrich_briefing_row_is_not_a_confirm_gate() -> None:
    row = enrich_briefing_row(
        {"symbol": "NVDA", "llm_bias": "偏多", "rule_bias": "中性", "health": "观察"},
        {"last_price": 130, "prior_close": 128, "delayed": "1", "source": "alpaca_iex"},
    )
    assert row["confirm_required"] is False
    assert row["active_bias"] == "偏多"
    assert row["active_bias_source"] == "llm"
    assert row["conclusion_price"] == 128
    assert row["conclusion_price_source"] == "prior_close"


def test_shell_hides_alerts_when_none() -> None:
    shell = build_shell(
        briefing={
            "date": "2026-09-04",
            "has_reviews": True,
            "session": {"is_trading_day": True},
            "rows": [{"symbol": "NVDA", "health": "趋势健康", "llm_status": "ok"}],
        },
        options={"status": "ok", "total_put_call": 0.8},
        impact={"macro": [{"narrative": "CPI 低于预期 → 通胀降温", "impacts": []}]},
        snapshots=[],
    )
    assert shell["alerts"] == []
    assert shell["explicit_state"]["code"] in {"missing", "clear"}
    assert shell["environment"]["one_liner"]
