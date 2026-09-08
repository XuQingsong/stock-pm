from stock_pm.analytics import (
    earnings_scorecard,
    growth_phase_label,
    judge_outcome,
    pick_outlook_bias,
    reconstructed_pe_view,
    return_1y_pct,
    rule_next_day_draft,
    tape_health,
    yoy_from_rows,
)
from stock_pm.llm import (
    complete_review,
    classify_llm_error,
    context_fingerprint,
    parse_llm_json,
    reuse_llm_if_unchanged,
    LLMRequestError,
)
from stock_pm.persist import PersistMixin
from stock_pm.providers import _growth_from_income


def test_return_1y_and_scorecard() -> None:
    bars = [{"close_price": 200}] + [{"close_price": 100}] * 251
    assert return_1y_pct(bars) == 100.0
    card = earnings_scorecard(
        [
            {"eps_actual": 2.0, "eps_estimate": 1.8, "revenue_actual": 10, "revenue_estimate": 9},
            {"eps_actual": 1.5, "eps_estimate": 1.6, "revenue_actual": 9, "revenue_estimate": None},
            {"eps_actual": 1.4, "eps_estimate": 1.2},
            {"eps_actual": 1.1, "eps_estimate": 1.0},
        ]
    )
    assert card["eps_beats"] == 3
    assert card["eps_scored"] == 4
    assert card["revenue_beats"] == 1
    assert card["revenue_scored"] == 1
    assert card["revenue_missing_estimate"] == 1


def test_yoy_and_growth_phase() -> None:
    rows = [
        {"fiscal_year": 2026, "fiscal_period": "Q2", "revenue_actual": 120, "eps_actual": 2.4},
        {"fiscal_year": 2026, "fiscal_period": "Q1", "revenue_actual": 110, "eps_actual": 2.2},
        {"fiscal_year": 2025, "fiscal_period": "Q4", "revenue_actual": 100, "eps_actual": 2.0},
        {"fiscal_year": 2025, "fiscal_period": "Q3", "revenue_actual": 95, "eps_actual": 1.8},
        {"fiscal_year": 2025, "fiscal_period": "Q2", "revenue_actual": 80, "eps_actual": 1.5},
    ]
    assert yoy_from_rows(rows, "revenue_actual") == 50.0
    assert growth_phase_label(50, 20) == "加速"
    assert growth_phase_label(-3, 10) == "转负"
    assert growth_phase_label(None) == "样本不足"
    assert growth_phase_label(18, 17) == "仍高增"


def test_reconstructed_pe_and_health() -> None:
    view = reconstructed_pe_view([30, 20, 10, 12, 14, 16, 18, 22, 24, 26], eps_ttm=1, pe_ttm=30)
    assert view["label"] == "偏高"
    assert view["samples"] == 10
    assert "回推" in view["basis"]
    assert tape_health({"rsi14": 80}, {}) == "过热"
    assert tape_health({"volume_ratio_20d": 0.5}, {}) == "缩量无方向"
    assert tape_health({"close_price": 120, "ma50": 100, "bullish_alignment": True}, {}) == "趋势健康"
    assert tape_health({}, {"breakout_status": "放量有效跌破"}) == "走坏"


def test_rule_draft_and_outcome() -> None:
    draft = rule_next_day_draft({"score": 40, "breakout": "区间内", "support": 10, "resistance": 12})
    assert draft["rule_bias"] == "偏多"
    assert judge_outcome("偏多", 1.2, False) == "符合"
    assert judge_outcome("偏多", -1.5, False) == "相反"
    assert judge_outcome("中性", 0.2, False) == "符合"
    assert pick_outlook_bias({"user_bias": "偏空", "llm_bias": "偏多", "rule_bias": "中性"}) == ("偏空", "user")
    assert pick_outlook_bias({"llm_bias": "偏多", "rule_bias": "中性"}) == ("偏多", "llm")


def test_parse_llm_json_and_missing_key() -> None:
    parsed = parse_llm_json('```json\n{"why":"量价配合","outlook":"观察压力","bias":"偏多","confidence":"medium"}\n```')
    assert parsed["why"] == "量价配合"
    assert parsed["bias"] == "偏多"
    from stock_pm.config import Settings

    result = complete_review({"symbol": "NVDA"}, Settings(llm_api_key=""))
    assert result["llm_status"] == "missing_key"
    assert result["llm_why"] is None


def test_classify_and_complete_quota_exhausted(monkeypatch) -> None:
    from stock_pm import llm
    from stock_pm.config import Settings

    assert classify_llm_error(402, "") == "quota_exhausted"
    assert classify_llm_error(429, '{"error":{"code":"insufficient_quota"}}') == "quota_exhausted"
    assert classify_llm_error(429, "rate limit exceeded") == "failed"

    def boom(_settings, _context):
        raise LLMRequestError(402, '{"error":{"message":"Insufficient Balance"}}')

    monkeypatch.setattr(llm, "_openai_complete", boom)
    result = complete_review(
        {"symbol": "NVDA"},
        Settings(llm_api_key="sk-test", llm_provider="openai", llm_model="deepseek-chat"),
    )
    assert result["llm_status"] == "quota_exhausted"
    assert "额度已用尽" in (result["llm_error"] or "")


def test_reuse_llm_if_unchanged() -> None:
    context = {"symbol": "AAPL", "tape": {"close": 1.23456789}, "news": []}
    fingerprint = context_fingerprint(context)
    assert fingerprint == context_fingerprint({"symbol": "AAPL", "tape": {"close": 1.234568}, "news": []})
    existing = {
        "llm_context_hash": fingerprint,
        "llm_status": "ok",
        "llm_why": "放量",
        "llm_outlook": "观察",
        "llm_bias": "偏多",
        "llm_model": "test-model",
    }
    _, cached = reuse_llm_if_unchanged(context, existing)
    assert cached is not None
    assert cached["llm_cached"] is True
    assert reuse_llm_if_unchanged(context, existing, force=True)[1] is None
    assert reuse_llm_if_unchanged({**context, "news": [{"headline": "new"}]}, existing)[1] is None
    assert reuse_llm_if_unchanged(context, {**existing, "llm_status": "failed"})[1] is None
    assert context_fingerprint(context, model="a") != context_fingerprint(context, model="b")


def test_environment_snapshot_sql_is_append_only() -> None:
    import inspect

    source = inspect.getsource(PersistMixin.append_environment_snapshot)
    assert "INSERT INTO environment_snapshots" in source
    assert "ON CONFLICT" not in source
    source = inspect.getsource(PersistMixin.append_severity_alerts)
    assert "INSERT INTO severity_alerts" in source
    assert "ON CONFLICT" not in source


def test_store_review_sql_preserves_user_fields() -> None:
    import inspect

    source = inspect.getsource(PersistMixin.store_review)
    assert "user_bias = EXCLUDED" not in source
    assert "user_outlook = EXCLUDED" not in source
    assert "llm_why = EXCLUDED.llm_why" in source
    assert "llm_context_hash = EXCLUDED.llm_context_hash" in source
    assert "llm_error = EXCLUDED.llm_error" in source


def test_growth_from_income_uses_year_ago_quarter() -> None:
    income = [
        {"revenue": 120, "eps": 2.4},
        {"revenue": 110, "eps": 2.2},
        {"revenue": 105, "eps": 2.1},
        {"revenue": 100, "eps": 2.0},
        {"revenue": 80, "eps": 1.5},
    ]
    revenue_yoy, eps_yoy, revenue_ttm = _growth_from_income(income)
    assert revenue_yoy == 50.0
    assert eps_yoy == 60.0
    assert revenue_ttm == 435
