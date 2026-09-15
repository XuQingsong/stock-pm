"""Main-path copy must speak investment meaning, not system self-justification."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_pm.environment import causal_one_liner, conclusion_from_stances, synthesize_symbol_environment
from stock_pm.pack.cards import focus_rows, stock_judge
from stock_pm.pack.copy import MAIN_PATH_BANNED, investorize, judgment_reason, main_path_violations
from stock_pm.pack.overview import build_overview_payload
from stock_pm.pack.review_page import build_review_payload, observe_card
from stock_pm.pack.stock_page import build_stock_payload
from stock_pm.ux_copy import named_missing_line


MAIN_PATH_STATIC = [
    Path("src/stock_pm/static/overview.html"),
    Path("src/stock_pm/static/review.html"),
    Path("src/stock_pm/static/stock.html"),
    Path("src/stock_pm/static/desk.js"),
]

MAIN_PATH_PACK = [
    Path("src/stock_pm/pack/overview.py"),
    Path("src/stock_pm/pack/stock_page.py"),
    Path("src/stock_pm/pack/review_page.py"),
    Path("src/stock_pm/pack/cards.py"),
    Path("src/stock_pm/pack/mapping.py"),
]

# Spoken on the page. Internal JSON keys may still exist on the wire.
SPOKEN_BANNED = tuple(
    phrase
    for phrase in MAIN_PATH_BANNED
    if phrase
    not in {
        "can_form_direction",
        "prediction_ready",
        "closed loop",
        "source tier",
        "rule v0",
        "evidence version",
    }
)

_SKIP_KEYS = {
    "alert_id",
    "prediction_id",
    "event_id",
    "id",
    "diagnostics",
    "closed_loop",
    "can_form_direction",
    "prediction_ready",
    "href",
    "url",
    "symbol",
}


def _spoken(value, *, key=None) -> str:
    if key in _SKIP_KEYS:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_spoken(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_spoken(item, key=inner) for inner, item in value.items())
    return ""


def test_brief_rewrites_system_rule_into_investment_meaning() -> None:
    assert investorize("宏观有标题未映射，不编方向") == "宏观信息暂未形成对该股的明确影响"
    assert "背景信息" in investorize("只作环境理解，不写成预测或打脸")
    assert "置信度有限" in investorize("缺口：估值、宏观消息，不补假数")
    assert "暂不形成可验证预测" in investorize("无法形成正式预测")
    assert "不计入预测准确率" in investorize("缺少窗口/边界，禁止进校验主口径")
    assert "can_form_direction" not in investorize("can_form_direction=false：缺匹配期限")


def test_environment_conclusions_are_investment_meaning() -> None:
    aligned = conclusion_from_stances("bull", "bull")
    assert "背景信息" in aligned
    assert main_path_violations(aligned) == []
    missing = causal_one_liner(None, None, None, None, missing_note="估值、宏观消息")
    assert "暂不提高置信度" in missing
    assert "不补" not in missing
    assert "不编" not in missing
    unmapped = synthesize_symbol_environment(
        as_of_date="2026-09-15",
        symbol="AAPL",
        watch={"themes": ["consumer_electronics"]},
        news=[{"symbol": "AAPL", "headline": "Random blog", "themes": ["consumer_electronics"], "impacts": []}],
    )
    clause = unmapped["struct"]["news"]["company"]["clause"]
    assert "明确影响" in clause
    assert main_path_violations(clause) == []


def test_stock_judge_is_three_layers() -> None:
    row = {
        "env_half": "盘面：趋势健康；消息：行业利多；因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。估值不足，暂不提高置信度。",
        "prediction": {"thesis": "因此：研究倾向偏多"},
    }
    judge = stock_judge(row, [])
    assert "研究倾向偏多" in judge["stance"]
    assert judge["actions"]
    assert "盘面：" not in judge["quote"]
    assert "缺口" not in judge["quote"]
    assert main_path_violations(judge["quote"]) == []
    assert "不改变现有判断" in judgment_reason(row["env_half"])


def test_named_missing_is_decision_consequence() -> None:
    line = named_missing_line(["window", "support", "fundamentals.valuation"])
    assert "缺时间窗" in line
    assert "不计入预测准确率" in line
    assert "未编造" not in line


def test_review_observation_is_not_acceptance_tone() -> None:
    card = observe_card({"thesis": "弱偏多", "state": "missing"}, "MU")
    blob = json.dumps(card, ensure_ascii=False)
    assert "观察" in card["title"]
    assert "不计入预测准确率" in card["text"]
    assert "禁止" not in blob
    assert "校验" not in blob
    assert "证据版本" not in blob
    assert "规则倾向" not in blob


def test_packed_pages_speak_investor_language() -> None:
    overview = build_overview_payload(watch=[{"symbol": "NVDA", "name": "NVIDIA", "active": True}], events=[], briefing={"rows": []})
    stock = build_stock_payload(
        symbol="NVDA",
        watch=[{"symbol": "NVDA", "name": "NVIDIA", "active": True}],
        briefing_row={"symbol": "NVDA", "env_half": "研究倾向偏多"},
        events=[],
        environment={"one_liner": "盘面：趋势健康；消息：行业利多；因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。"},
        env_history=[],
        tape={},
        prediction={"state": "missing", "prediction_ready": False},
        decision={},
    )
    review = build_review_payload(
        watch=[{"symbol": "MU"}],
        predictions={"MU": [{"symbol": "MU", "state": "missing", "prediction_ready": False, "thesis": "弱偏多"}]},
        checks={},
        today=date(2026, 9, 15),
    )
    spoken = "\n".join(_spoken(payload) for payload in (overview, stock, review))
    for phrase in SPOKEN_BANNED:
        assert phrase not in spoken, phrase
    assert "证据版本" not in spoken
    focus = focus_rows(
        [{"symbol": "NVDA", "name": "NVIDIA"}],
        [{"symbol": "NVDA", "env_half": "盘面：走坏；消息：宏观利空；因此：盘面与消息同向，当前仅作为背景信息，不改变现有判断。"}],
        [],
    )
    why = (focus["skip"] or focus["watch"] or focus["priority"] or [{}])[0].get("why") or ""
    assert "盘面：" not in why
    assert main_path_violations(why) == []


def test_main_path_static_and_pack_ban_forbidden_phrases() -> None:
    for path in MAIN_PATH_STATIC + MAIN_PATH_PACK:
        text = path.read_text(encoding="utf-8")
        for phrase in SPOKEN_BANNED:
            if phrase in {"不编", "不补"}:
                continue
            assert phrase not in text, f"{path}: {phrase}"
        assert "本页不出现" not in text
        assert "禁止进校验" not in text
        assert "字段齐全" not in text
