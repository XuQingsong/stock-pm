from stock_pm.tape import (
    REVIEW_UNEXPLAINED,
    TAPE_FIELD_FLAGS,
    TAPE_MISSING_LINE,
    TAPE_PLACEHOLDER,
    env_tape_conflict_sentence,
    failed_tape,
    is_env_tape_conflict_sentence,
    synthesize_review_note,
    synthesize_tape_analysis,
    tape_half_display,
    volume_price_form,
)


def _metrics(**overrides) -> dict:
    base = {
        "day_change_pct": -4.2,
        "relative_volume": 1.8,
        "tape": "放量下杀，收盘靠近最低价，卖盘主导",
        "breakout": "放量有效跌破",
        "support_test": "收盘跌破最近支撑",
        "close_location": 0.18,
        "poc_60d": 130.0,
        "value_area_low": 122.0,
        "value_area_high": 138.0,
        "support": 124.0,
        "resistance": 136.0,
        "position": "大部分60日成交筹码位于现价上方，套牢抛压较重",
        "ma5": 128.0,
        "ma20": 131.0,
        "ma50": 129.0,
        "ma200": 110.0,
        "close": 120.0,
    }
    base.update(overrides)
    return base


def _bear_env() -> dict:
    return {
        "one_liner": "盘面：走坏；消息：宏观利空（加息预期升温）；因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。",
        "struct": {
            "fundamentals": {"year_move": {"clause": "过去一年约跌 12.0%"}},
            "news": {
                "macro": {
                    "bias": "利空",
                    "headline": "加息预期升温",
                    "clause": "宏观偏利空：加息预期升温",
                },
                "sector": {
                    "bias": "利空",
                    "headline": "存储去杠杆",
                    "clause": "行业偏利空：存储去杠杆",
                },
                "company": None,
            },
            "sentiment": {"atmosphere": "恐慌", "clause": "近20日 -16.0%，氛围偏恐慌"},
        },
        "missingFlags": [],
        "publishState": "published",
    }


def _bull_env() -> dict:
    return {
        "one_liner": "盘面：趋势健康；消息：行业利多（缺货延续）；因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。",
        "struct": {
            "fundamentals": {"year_move": {"clause": "过去一年约涨 42.5%"}},
            "news": {
                "macro": None,
                "sector": {
                    "bias": "利多",
                    "headline": "行业缺货延续",
                    "clause": "行业偏利多：行业缺货延续",
                },
                "company": {
                    "bias": "利多",
                    "headline": "云厂商扩大合作",
                    "clause": "公司偏利多：云厂商扩大合作",
                },
            },
            "sentiment": {"atmosphere": "补涨", "clause": "近5日 +6.0%，氛围偏补涨"},
        },
        "missingFlags": [],
        "publishState": "published",
    }


def test_volume_price_is_judgment_not_raw_volume() -> None:
    assert volume_price_form(2.1, 1.5) == ("放量涨", False)
    assert volume_price_form(1.0, 0.6) == ("缩量涨", False)
    assert volume_price_form(-2.0, 1.7) == ("放量跌", False)
    assert volume_price_form(-1.2, 0.5) == ("缩量跌", False)
    assert volume_price_form(None, 1.5) == (None, True)
    assert volume_price_form(2.0, None) == (None, True)


def test_tape_answers_acceptance_m2_questions() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="MU",
        metrics=_metrics(),
        environment=_bear_env(),
        source="test",
    )
    answers = tape["struct"]["answers"]
    assert tape["volume_price"]["form"] == "放量跌"
    assert answers["q1_volume_price"] == "放量跌"
    assert "130" in answers["q2_chips"]
    assert "支撑" in answers["q2_chips"] and "压力" in answers["q2_chips"]
    assert "MA5" in answers["q2_chips"] and "MA200" in answers["q2_chips"]
    assert tape["break"]["aftermath"] == "续杀"
    assert "续杀" in answers["q3_break"]
    assert tape["env_link"]["judgment"] == "逃跑"
    assert tape["env_link"]["inferred"] is True
    assert "加息预期升温" in answers["q4_env_link"] or "恐慌" in answers["q4_env_link"]
    assert "推断" in answers["q4_env_link"]
    assert tape["one_liner"] != TAPE_PLACEHOLDER
    assert tape["publishState"] == "published"
    assert tape["prediction_ready"] is False


def test_tape_env_link_is_not_tape_restatement() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="NVDA",
        metrics=_metrics(
            day_change_pct=4.5,
            relative_volume=1.9,
            breakout="放量有效突破",
            support_test="未测试最近支撑",
            close_location=0.86,
            tape="放量上攻，收盘靠近最高价，买盘主导",
        ),
        environment=_bear_env(),
    )
    assert tape["volume_price"]["form"] == "放量涨"
    assert tape["env_link"]["judgment"] == "诱多"
    clause = tape["env_link"]["clause"]
    assert "环境" in clause
    assert "诱多" in clause
    assert clause != tape["volume_price"]["clause"]
    assert tape["conflict"] is True
    assert tape["weak_vs_env"]["status"] == "missing"
    assert "暂不能判断是否弱于环境" in tape["weak_vs_env"]["clause"]
    assert "不编造" not in tape["weak_vs_env"]["clause"]
    assert "推断" not in (tape["weak_vs_env"]["clause"] or "")


def test_honest_missing_chips_and_env() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="INTC",
        metrics={"day_change_pct": 1.2, "relative_volume": 0.5},
        environment={"struct": {}, "missingFlags": ["news.macro"]},
    )
    assert tape["volume_price"]["form"] == "缩量涨"
    assert "chips" in tape["missingFlags"]
    assert "筹码带与支撑压力暂缺" in tape["struct"]["answers"]["q2_chips"]
    assert "env_link" in tape["missingFlags"]
    assert "暂不判断诱多" in tape["struct"]["answers"]["q4_env_link"]
    assert "不编" not in tape["struct"]["answers"]["q4_env_link"]


def test_break_aftermath_pullback_and_fake_break() -> None:
    pullback = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="AAPL",
        metrics=_metrics(
            breakout="跌破后收回",
            support_test="盘中测试支撑后收回",
            day_change_pct=-0.4,
            relative_volume=1.3,
        ),
        environment=_bear_env(),
    )
    assert pullback["break"]["aftermath"] == "拉回"

    fake = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="AAPL",
        metrics=_metrics(
            day_change_pct=0.8,
            relative_volume=1.4,
            breakout="冲高突破失败",
            support_test="未测试最近支撑",
            close_location=0.35,
        ),
        environment=_bull_env(),
    )
    assert fake["break"]["aftermath"] == "假突破"


def test_review_note_vernacular_and_causal_or_unexplained() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="MU",
        metrics=_metrics(),
        environment=_bear_env(),
    )
    note = synthesize_review_note(
        as_of_date="2026-09-04",
        symbol="MU",
        tape=tape,
        environment=_bear_env(),
    )
    assert "放量跌" in note["summary"]
    assert "续杀" in note["summary"]
    assert note["unexplained"] is False
    text = note["explanation"]
    assert text.index("环境") < text.index("昨盘") < text.index("因此")
    assert "可能相关" not in text
    assert note["prediction_ready"] is False

    empty = synthesize_review_note(
        as_of_date="2026-09-04",
        symbol="INTC",
        tape=synthesize_tape_analysis(
            as_of_date="2026-09-04",
            symbol="INTC",
            metrics=_metrics(),
            environment={"struct": {}},
        ),
        environment={"struct": {}},
    )
    assert empty["unexplained"] is True
    assert empty["explanation"] == REVIEW_UNEXPLAINED


def test_conflict_row_is_one_causal_sentence() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="NVDA",
        metrics=_metrics(
            day_change_pct=3.8,
            relative_volume=1.7,
            breakout="放量有效突破",
            support_test="未测试最近支撑",
            close_location=0.8,
        ),
        environment=_bear_env(),
    )
    assert tape["conflict"] is True
    sentence = env_tape_conflict_sentence(_bear_env(), tape)
    assert is_env_tape_conflict_sentence(sentence)
    assert sentence.count("。") == 1
    assert "方向相反" in sentence
    assert "先按昨盘收盘读" in sentence
    assert "可能相关" not in sentence


def test_failed_tape_is_visible_missing() -> None:
    snap = failed_tape("MU", "2026-09-04", "bars missing")
    assert snap["publishState"] == "missing"
    assert snap["missingFlags"] == list(TAPE_FIELD_FLAGS)
    assert TAPE_MISSING_LINE in snap["one_liner"]
    assert snap["volume_price"] is None


def test_tape_half_display_never_fakes_form() -> None:
    assert tape_half_display(None) == TAPE_PLACEHOLDER
    assert tape_half_display({"publishState": "missing", "one_liner": TAPE_MISSING_LINE}) == TAPE_MISSING_LINE
    real = {"publishState": "published", "one_liner": "放量跌，续杀，逃跑（推断）"}
    assert tape_half_display(real) == "放量跌，续杀，逃跑（推断）"


def _relative(**overrides) -> dict:
    base = _metrics(
        benchmark_kind="sector",
        benchmark_name="板块（半导体/AI）",
        benchmark_day_change_pct=-1.0,
        return_5d_pct=-6.0,
        benchmark_return_5d_pct=-2.0,
    )
    base.update(overrides)
    return base


def test_weak_vs_env_requires_lag_and_break_or_volume_down() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="MU",
        metrics=_relative(day_change_pct=-4.2, relative_volume=1.8),
        environment=_bear_env(),
    )
    weak = tape["weak_vs_env"]
    assert weak is not None
    assert "weak_vs_env" not in tape["missingFlags"]
    assert weak["status"] == "weak"
    assert weak["inferred"] is False
    assert weak["benchmark"] == "板块（半导体/AI）"
    assert weak["benchmark_kind"] == "sector"
    assert weak["prior_relative_return_pct"] == -3.2
    assert weak["lags_significantly"] is True
    assert weak["volume_down"] is True
    assert weak["structure_or_volume_down"] is True
    assert "推断" not in weak["clause"]
    assert "弱于环境" in weak["clause"]
    assert "conflict" not in weak
    assert weak["facts_line"].startswith("基准 ")
    assert "昨收相对" in weak["facts_line"]
    assert "破位或放量跌" in weak["facts_line"]
    assert "结论 弱于环境" in weak["facts_line"]
    assert tape["struct"]["answers"]["q5_weak_vs_env"] == weak["clause"]


def test_weak_vs_env_same_direction_beta_is_not_weak() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="MU",
        metrics=_relative(
            day_change_pct=-3.2,
            benchmark_day_change_pct=-3.0,
            return_5d_pct=-5.0,
            benchmark_return_5d_pct=-4.8,
            relative_volume=1.8,
        ),
        environment=_bear_env(),
    )
    weak = tape["weak_vs_env"]
    assert weak["status"] == "not_weak"
    assert weak["lags_significantly"] is False
    assert weak["volume_down"] is True
    assert "同向贝塔" in weak["clause"]
    assert "不等于弱于环境" in weak["clause"]
    assert "偏弱" not in weak["clause"]


def test_weak_vs_env_form_vs_env_conflict_is_not_the_field() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="NVDA",
        metrics=_relative(
            day_change_pct=4.5,
            relative_volume=1.9,
            benchmark_day_change_pct=-1.0,
            return_5d_pct=2.0,
            benchmark_return_5d_pct=-1.0,
            breakout="放量有效突破",
            support_test="未测试最近支撑",
            close_location=0.86,
        ),
        environment=_bear_env(),
    )
    assert tape["volume_price"]["form"] == "放量涨"
    assert tape["env_link"]["judgment"] == "诱多"
    assert tape["conflict"] is True
    assert tape["weak_vs_env"]["status"] != "weak"
    assert tape["weak_vs_env"]["inferred"] is False


def test_weak_vs_env_missing_relative_is_honest() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="INTC",
        metrics=_metrics(),
        environment=_bear_env(),
    )
    weak = tape["weak_vs_env"]
    assert "weak_vs_env" in tape["missingFlags"]
    assert weak["status"] == "missing"
    assert "暂不能判断是否弱于环境" in weak["clause"]
    assert "不编造" not in weak["clause"]
    assert "推断" not in weak["clause"]
    assert weak["prior_relative_return_pct"] is None
    assert "结论 无法判定" in weak["facts_line"]
    assert "conflict" not in weak


def test_weak_vs_env_lag_without_break_or_volume_down_is_not_weak() -> None:
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol="AAPL",
        metrics=_relative(
            day_change_pct=-2.5,
            benchmark_day_change_pct=-0.4,
            relative_volume=0.9,
            breakout="未破位",
            support_test="",
            close_location=0.5,
        ),
        environment=_bear_env(),
    )
    weak = tape["weak_vs_env"]
    assert weak["status"] == "not_weak"
    assert weak["lags_significantly"] is True
    assert weak["volume_down"] is False
    assert "不判定弱于环境" in weak["clause"]
