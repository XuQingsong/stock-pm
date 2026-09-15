"""Main-path copy must speak investment meaning, not system self-justification.

Permanent ban: overview / stock / review must never again show DEV_BRIEF
system/acceptance/diagnostic self-talk. Diagnostic and expand-evidence may.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_pm.environment import causal_one_liner, conclusion_from_stances, synthesize_symbol_environment
from stock_pm.pack.cards import event_card, focus_rows, stock_judge
from stock_pm.pack.copy import MAIN_PATH_BANNED, investorize, judgment_reason, main_path_violations
from stock_pm.pack.overview import build_overview_payload
from stock_pm.pack.review_page import build_review_payload, observe_card
from stock_pm.pack.stock_page import build_stock_payload
from stock_pm.ux_copy import display_title, drop_english_headlines, named_missing_line


MAIN_PATH_STATIC = [
    Path("src/stock_pm/static/overview.html"),
    Path("src/stock_pm/static/review.html"),
    Path("src/stock_pm/static/stock.html"),
    Path("src/stock_pm/static/stock.js"),
    Path("src/stock_pm/static/desk.js"),
    Path("design-hifi/overview.html"),
    Path("design-hifi/review.html"),
    Path("design-hifi/stock.html"),
]

MAIN_PATH_PACK = [
    Path("src/stock_pm/pack/overview.py"),
    Path("src/stock_pm/pack/stock_page.py"),
    Path("src/stock_pm/pack/review_page.py"),
    Path("src/stock_pm/pack/cards.py"),
    Path("src/stock_pm/pack/mapping.py"),
]

MAIN_PATH_ORIGIN = [
    Path("src/stock_pm/environment.py"),
    Path("src/stock_pm/tape.py"),
    Path("src/stock_pm/philosophy.py"),
    Path("src/stock_pm/prediction.py"),
    Path("src/stock_pm/events/exposure.py"),
]

# Phrases that must never appear as main-path UI copy, including short stems.
# Wire keys may exist in Python comments/JSON; they are not file-scanned here.
FILE_BANNED = (
    "不编",
    "不补",
    "禁止",
    "未编造",
    "未编达标",
    "编出来",
    "字段齐全",
    "本页不出现",
    "本页不展开",
    "抓取失败",
    "抓取状态",
    "API 未配置",
    "L0",
    "L1",
    "L2",
    "L3",
)

# Spoken on the page. Internal JSON keys may still exist on the wire.
SPOKEN_BANNED = tuple(
    phrase
    for phrase in MAIN_PATH_BANNED
    if phrase
    not in {
        "can_form_direction",
        "prediction_ready",
        "closed loop",
        "closed_loop",
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
    "basis",
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
    assert "L0" not in investorize("当前可用等级 L0")
    assert "禁止" not in investorize("证据不足，禁止生成无来源数字或价格预测")
    assert "不形成方向" not in investorize("正文摘录不支持当前事实，不形成方向")
    assert "risk_state" not in investorize("affects risk_state")
    assert "市场波动风险" in investorize("VIX 只确认风险状态")
    assert main_path_violations(investorize("证据不足，禁止生成无来源数字或价格预测")) == []


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


def test_main_path_drops_english_headline_walls() -> None:
    assert drop_english_headlines("宏观偏利多：Profits surge to record high") == "宏观偏利多"
    assert "Profits" not in drop_english_headlines(
        "盘面：走坏；消息：行业利多（Profits surge to record high）；因此：当前先按盘面读。"
    )
    assert display_title("AVGO and MSFT mentioned while NVDA reports orders") == "相关新闻"
    env = synthesize_symbol_environment(
        as_of_date="2026-09-15",
        symbol="MU",
        watch={"themes": ["semis"]},
        news=[
            {
                "symbol": "MU",
                "headline": "Profits surge to record high",
                "themes": ["semis"],
                "impacts": [{"theme": "semis", "direction": "利多", "symbols": ["MU"]}],
            }
        ],
    )
    spoken = "\n".join([env["one_liner"], env["row_thesis"], env["struct"]["news"]["company"]["clause"]])
    assert "Profits surge" not in spoken
    overview = build_overview_payload(
        watch=[{"symbol": "NVDA", "name": "NVIDIA", "active": True}],
        events=[],
        briefing={"rows": []},
        news=[
            {
                "symbol": "NVDA",
                "headline": "AVGO and MSFT mentioned while NVDA reports orders",
                "themes": ["semis"],
                "summary": "订单超预期",
            }
        ],
    )
    titles = " ".join(card["title"] for card in overview["carousel"])
    assert "reports orders" not in titles
    assert "订单" in titles or "相关新闻" in titles
    stock = build_stock_payload(
        symbol="NVDA",
        watch=[{"symbol": "NVDA", "active": True}],
        briefing_row={"symbol": "NVDA"},
        events=[],
        environment={"one_liner": "消息：行业利多（Profits surge to record high）；因此：当前仅作为背景信息，不改变现有判断。"},
        env_history=[],
        tape={},
        prediction={},
        decision={"thesis": {"direction": "bullish", "invalidation": "L0 缺口", "bull_drivers": [{"text": "system-risk 上升"}]}},
    )
    spoken_stock = _spoken(stock)
    assert "Profits surge" not in spoken_stock
    assert "L0" not in spoken_stock
    assert "system-risk" not in spoken_stock


def test_event_card_drops_withheld_diagnostics_from_conclusion() -> None:
    card = event_card(
        {
            "canonical_title": "Some English Headline About Inventories",
            "analysis": {
                "withheld": {"status": "withheld", "reason": "证据不足，禁止生成无来源数字或价格预测"},
                "closed_loop": False,
                "answers": {"what_happened": "规则 rule_id。方向 withheld"},
                "mechanism": {"text": "禁止用 VIX 单独推翻或成立价格方向。"},
            },
        },
        [{"symbol": "NVDA", "name": "NVIDIA", "active": True}],
    )
    spoken = " ".join([card.get("title") or "", card.get("conclusion") or "", card.get("transmit") or ""])
    assert "禁止" not in spoken
    assert "withheld" not in spoken
    assert "rule_id" not in spoken
    assert "Some English Headline" not in (card.get("title") or "")
    assert main_path_violations(spoken) == []


def test_main_path_static_and_pack_ban_forbidden_phrases() -> None:
    for path in MAIN_PATH_STATIC + MAIN_PATH_PACK + MAIN_PATH_ORIGIN:
        text = path.read_text(encoding="utf-8")
        for phrase in FILE_BANNED:
            assert phrase not in text, f"{path}: {phrase}"
        assert "本页不出现" not in text
        assert "禁止进校验" not in text
        assert "字段齐全" not in text


def test_packed_pages_never_speak_banned_stems() -> None:
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
        decision={"thesis": {"direction": "bullish", "invalidation": "L0 缺口", "bull_drivers": [{"text": "system-risk 上升"}]}},
    )
    review = build_review_payload(
        watch=[{"symbol": "MU"}],
        predictions={"MU": [{"symbol": "MU", "state": "missing", "prediction_ready": False, "thesis": "弱偏多"}]},
        checks={},
        today=date(2026, 9, 15),
    )
    spoken = "\n".join(_spoken(payload) for payload in (overview, stock, review))
    for stem in ("不编", "不补", "禁止", "抓取", "L0", "withheld", "prediction_ready", "API"):
        assert stem not in spoken, stem
    assert "Profits surge" not in spoken
