from datetime import date

from stock_pm.calendar import add_trading_days, next_trading_day
from stock_pm.prediction import (
    QUALIFIED_EXAMPLE,
    apply_supersede,
    failed_prediction,
    has_real_bounds,
    mark_legacy_hit_rate,
    prediction_badge,
    prediction_hit_rate,
    run_prediction_check,
    synthesize_prediction,
)
from stock_pm.tape import synthesize_review_note, synthesize_tape_analysis


def _env(atmosphere: str = "补涨") -> dict:
    return {
        "as_of_date": "2026-09-04",
        "one_liner": "盘面：缩量跌；消息：行业利多（行业缺货延续）；因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。",
        "synthesis": "盘面：缩量跌；消息：行业利多（行业缺货延续）；因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。",
        "publishState": "published",
        "missingFlags": [],
        "struct": {"sentiment": {"atmosphere": atmosphere, "clause": f"氛围{atmosphere}"}},
        "prediction_ready": False,
    }


def _tape(
    *,
    day_change_pct: float = -1.2,
    relative_volume: float = 0.6,
    support: float = 19.0,
    resistance: float = 22.0,
    close: float = 20.0,
    judgment: str = "吸筹",
) -> dict:
    return synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="INTC",
        metrics={
            "day_change_pct": day_change_pct,
            "relative_volume": relative_volume,
            "poc_60d": 19.5,
            "support": support,
            "resistance": resistance,
            "close": close,
            "position": "筹码在现价附近",
        },
        environment=_env(),
        source="test",
    )


def _note(tape: dict) -> dict:
    return synthesize_review_note(
        as_of_date="2026-09-04",
        symbol="INTC",
        tape=tape,
        environment=_env(),
        source="test",
    )


def test_qualified_example_has_window_and_both_bounds() -> None:
    tape = _tape()
    tape["chips"] = {**(tape.get("chips") or {}), "close": 20.0}
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    assert pred["prediction_ready"] is True
    assert pred["state"] == "pending"
    assert pred["window_label"] == "两周内"
    assert pred["window_days"] == 10
    assert pred["window_start"] == "2026-09-08"
    assert pred["window_end"] == add_trading_days(date(2026, 9, 8), 9).isoformat()
    assert pred["upside_bound_pct"] == 10.0
    assert pred["downside_bound_pct"] == -5.0
    assert QUALIFIED_EXAMPLE in pred["thesis"]
    assert pred["thesis"].startswith("环境：")
    assert "昨盘：" in pred["thesis"]
    assert "解释：" in pred["thesis"]
    assert "因此：" in pred["thesis"]
    assert has_real_bounds(pred)
    assert "10%" in pred["badge"]
    assert "5%" in pred["badge"]


def test_quality_gate_failure_is_visible_missing() -> None:
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment={"publishState": "missing", "one_liner": None},
        tape={"publishState": "missing", "volume_price": None, "chips": {}},
        review_note={"unexplained": True},
        entry_price=None,
    )
    assert pred["state"] == "missing"
    assert pred["prediction_ready"] is False
    assert pred["upside_bound_pct"] is None
    assert pred["downside_bound_pct"] is None
    assert "缺数" in pred["missing_label"]
    assert "未编造" in pred["one_liner"]
    assert prediction_badge(pred) == pred["missing_label"]
    assert prediction_badge(None) == "到期未产出"


def test_does_not_invent_bounds_without_support_resistance() -> None:
    tape = _tape(support=None, resistance=None)
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=None,
        resistance=None,
    )
    assert pred["prediction_ready"] is False
    assert pred["upside_bound_pct"] is None
    assert "10%" not in (pred.get("thesis") or "")
    assert "缺数" in pred["missing_label"]


def test_state_machine_auto_gen_pending_active_hit() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    life = [item["state"] for item in pred["struct"]["lifecycle"]]
    assert life[:2] == ["auto_gen", "pending"]
    check = run_prediction_check(
        pred,
        as_of_date="2026-09-08",
        close=20.4,
        high=20.6,
        low=19.8,
    )
    assert check["prediction"]["state"] == "active"
    assert check["outcome"] == "tracking"
    assert check["alert"] is None
    hit = run_prediction_check(
        check["prediction"],
        as_of_date="2026-09-09",
        close=22.1,
        high=22.2,
        low=20.5,
        prior_max_gain_pct=check["max_gain_pct"],
        prior_max_drawdown_pct=check["max_drawdown_pct"],
    )
    assert hit["outcome"] == "hit"
    assert hit["prediction"]["state"] == "hit"
    assert hit["alert"] is None


def test_face_slap_on_downside_break_not_small_noise() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    pred["id"] = 7
    noise = run_prediction_check(
        pred, as_of_date="2026-09-08", close=19.7, high=20.1, low=19.6
    )
    assert noise["prediction"]["state"] == "active"
    assert noise["in_bounds"] is True
    assert noise["alert"] is None
    slap = run_prediction_check(
        noise["prediction"],
        as_of_date="2026-09-09",
        close=18.8,
        high=19.5,
        low=18.7,
    )
    assert slap["outcome"] == "downside_break"
    assert slap["prediction"]["state"] == "invalidated"
    assert slap["alert"]["severity"] == "severe"
    assert slap["alert"]["cta"] == "judgment_change"
    assert "打脸" in slap["alert"]["message"]


def test_expired_window_is_face_slap() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    end = pred["window_end"]
    check = run_prediction_check(
        pred, as_of_date=end, close=20.2, high=20.4, low=19.6
    )
    assert check["outcome"] == "expired"
    assert check["prediction"]["state"] == "invalidated"
    assert check["alert"]["cta"] == "judgment_change"


def test_missing_price_does_not_silently_pass() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    check = run_prediction_check(pred, as_of_date="2026-09-08", close=None)
    assert check["outcome"] == "missing_price"
    assert check["prediction"]["state"] == "active"
    assert "不改口" in check["reason"]


def test_human_supersede_leaves_trace_and_is_not_automatic() -> None:
    tape = _tape()
    old = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    old["id"] = 3
    new = synthesize_prediction(
        as_of_date="2026-09-09",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=19.5,
        support=18.5,
        resistance=21.5,
        source="human",
        change_reason="公开持仓大幅增加，原下跌边界不再适用",
    )
    superseded, replacement = apply_supersede(
        old, new, change_reason="公开持仓大幅增加，原下跌边界不再适用"
    )
    assert superseded["state"] == "superseded"
    assert superseded["change_reason"]
    assert replacement["supersedes_id"] == 3
    assert replacement["source"] == "human"
    assert "公开持仓" in replacement["struct"]["supersedes"]["reason"]
    try:
        apply_supersede(old, new, change_reason="  ")
        raise AssertionError("empty reason must fail")
    except ValueError as exc:
        assert "留痕" in str(exc)


def test_badge_never_fakes_bounds() -> None:
    missing = failed_prediction("MU", "2026-09-04", "quality_gate")
    assert "10%" not in prediction_badge(missing)
    assert "5%" not in prediction_badge(missing)
    assert has_real_bounds(missing) is False


def test_legacy_hit_rate_is_labeled() -> None:
    legacy = mark_legacy_hit_rate(
        {"all": {"samples": 2, "hits": 1, "rate_pct": 50.0}, "confirm_required": False}
    )
    assert legacy["legacy"] is True
    assert legacy["label"] == "旧口径"
    assert "不是新 Prediction" in legacy["disclaimer"]
    fresh = prediction_hit_rate(
        [{"state": "hit"}, {"state": "invalidated"}, {"state": "missing"}]
    )
    assert fresh["legacy"] is False
    assert fresh["samples"] == 2
    assert fresh["hits"] == 1
    assert fresh["face_slaps"] == 1


def test_downside_break_wins_same_day_over_hit() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    both = run_prediction_check(
        pred, as_of_date="2026-09-08", close=21.0, high=22.5, low=18.5
    )
    assert both["prediction"]["state"] == "invalidated"
    assert both["outcome"] == "downside_break"


def test_next_trading_day_skips_labor_day_2026() -> None:
    assert next_trading_day(date(2026, 9, 4)) == date(2026, 9, 8)
