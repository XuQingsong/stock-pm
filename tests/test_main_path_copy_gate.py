"""Permanent main-path copy gate.

Fails CI if overview / stock / review templates or copy-helper output still
contain DEV_BRIEF system/acceptance tokens. Diagnostic-only files (stock_diag.js,
shell.js, events_ui.js, settings) may mention tech terms; they are not gated.
stock.js is on the investor main path and IS gated.
"""

from __future__ import annotations

import ast
from pathlib import Path

from stock_pm.environment import synthesize_symbol_environment
from stock_pm.pack.cards import event_card, news_card
from stock_pm.pack.copy import (
    HORIZON_ENUM_TOKENS,
    MAIN_PATH_BANNED,
    MAIN_PATH_GATE_TOKENS,
    horizon_label,
    investorize,
    judgment_reason,
    main_path_copy,
    main_path_violations,
)
from stock_pm.pack.overview import build_overview_payload
from stock_pm.pack.review_page import build_review_payload
from stock_pm.pack.stock_page import build_stock_payload
from stock_pm.ux_copy import (
    carousel_label_ok,
    display_title,
    is_english_headline,
    is_price_like,
    is_readable_chinese,
)

ROOT = Path(__file__).resolve().parents[1]

# Main investment templates. Every string here can render to the user.
MAIN_PATH_TEMPLATES = (
    ROOT / "src/stock_pm/static/overview.html",
    ROOT / "src/stock_pm/static/stock.html",
    ROOT / "src/stock_pm/static/review.html",
    ROOT / "src/stock_pm/static/desk.js",
    ROOT / "src/stock_pm/static/stock.js",
    ROOT / "design-hifi/overview.html",
    ROOT / "design-hifi/stock.html",
    ROOT / "design-hifi/review.html",
)

# Page builders + origin copy that feed the main path. copy.py is the denylist
# itself (rewrite table + gate tokens) and is checked via helper *output*.
MAIN_PATH_HELPERS = (
    ROOT / "src/stock_pm/pack/overview.py",
    ROOT / "src/stock_pm/pack/stock_page.py",
    ROOT / "src/stock_pm/pack/review_page.py",
    ROOT / "src/stock_pm/pack/cards.py",
    ROOT / "src/stock_pm/pack/mapping.py",
    ROOT / "src/stock_pm/environment.py",
    ROOT / "src/stock_pm/tape.py",
    ROOT / "src/stock_pm/philosophy.py",
    ROOT / "src/stock_pm/prediction.py",
    ROOT / "src/stock_pm/events/exposure.py",
    ROOT / "src/stock_pm/ux_copy.py",
)

# Not gated: diagnostic fold / events center / settings.
DIAGNOSTIC_ONLY = (
    ROOT / "src/stock_pm/static/stock_diag.js",
    ROOT / "src/stock_pm/static/shell.js",
    ROOT / "src/stock_pm/static/events_ui.js",
    ROOT / "src/stock_pm/static/events.js",
    ROOT / "src/stock_pm/static/settings.html",
)

WIRE_KEYS_ONLY = {
    "prediction_ready",
    "can_form_direction",
    "closed_loop",
    "evidence_version",
    "alert_id",
    "direction_withheld",
}

# UI stems that must not appear even as Python string literals (except exact wire keys).
HELPER_SOURCE_STEMS = (
    "不编",
    "不补",
    "禁止",
    "未编造",
    "抓取失败",
    "API未配置",
    "API 未配置",
    "closed loop",
    "evidence version",
)

_SKIP_SPOKEN = {
    "alert_id",
    "prediction_id",
    "event_id",
    "id",
    "diagnostics",
    "basis",
    "closed_loop",
    "can_form_direction",
    "prediction_ready",
    "evidence_version",
    "href",
    "url",
    "symbol",
    "source_title",
}

_BANNED_FEED = (
    "宏观有标题未映射，不编方向",
    "缺口：估值，不补假数",
    "禁止进校验主口径",
    "API 未配置",
    "API未配置",
    "抓取失败",
    "closed loop invalid",
    "prediction_ready=false",
    "can_form_direction=false：缺匹配期限",
    "evidence version v3",
    "当前可用等级 L0",
    "L0 缺口",
    "days_to_weeks",
    "期限 days_to_weeks",
    "数据源暂未提供",
)


def _spoken(value, *, key=None) -> str:
    if key in _SKIP_SPOKEN:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_spoken(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_spoken(item, key=inner) for inner, item in value.items())
    return ""


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def test_gate_tokens_are_the_permanent_denylist() -> None:
    blob = " ".join(MAIN_PATH_BANNED)
    for token in MAIN_PATH_GATE_TOKENS:
        if token in {"closed_loop", "evidence_version", "can_form", "API未配置"}:
            continue
        assert token in MAIN_PATH_BANNED or token in blob, token


def test_main_path_templates_contain_no_gate_tokens() -> None:
    for path in MAIN_PATH_TEMPLATES:
        text = path.read_text(encoding="utf-8")
        for token in MAIN_PATH_GATE_TOKENS:
            assert token not in text, f"{path.relative_to(ROOT)}: {token!r}"
        for extra in ("L1", "L2", "L3", "本页不出现", "字段齐全", "不形成方向", "当前可用等级"):
            assert extra not in text, f"{path.relative_to(ROOT)}: {extra!r}"
    stock_js = (ROOT / "src/stock_pm/static/stock.js").read_text(encoding="utf-8")
    assert "数据源" not in stock_js
    assert "can_form" not in stock_js
    assert "L0" not in stock_js
    html = (ROOT / "src/stock_pm/static/stock.html").read_text(encoding="utf-8")
    assert "/static/stock_diag.js" in html


def test_copy_helpers_never_emit_gate_tokens() -> None:
    for raw in _BANNED_FEED:
        for fn in (investorize, main_path_copy, judgment_reason):
            out = fn(raw)
            for token in MAIN_PATH_GATE_TOKENS:
                assert token not in out, f"{fn.__name__}({raw!r}) -> {out!r} still has {token!r}"
            assert main_path_violations(out) == []


def test_helper_source_literals_are_not_acceptance_copy() -> None:
    for path in MAIN_PATH_HELPERS:
        for literal in _string_literals(path):
            if literal in WIRE_KEYS_ONLY:
                continue
            for stem in HELPER_SOURCE_STEMS:
                assert stem not in literal, f"{path.relative_to(ROOT)}: {stem!r} in {literal!r}"
            if literal in WIRE_KEYS_ONLY:
                continue
            for token in ("prediction_ready", "closed_loop", "evidence_version", "can_form_direction"):
                if token in literal and literal != token:
                    raise AssertionError(
                        f"{path.relative_to(ROOT)}: {token!r} spoken in {literal!r}"
                    )


def test_packed_thesis_fields_have_no_english_headline_walls() -> None:
    env = synthesize_symbol_environment(
        as_of_date="2026-09-15",
        symbol="MU",
        watch={"themes": ["semis"]},
        news=[
            {
                "symbol": "MU",
                "headline": "Profits surge to record high after export curbs ease",
                "themes": ["semis"],
                "impacts": [{"theme": "semis", "direction": "利多", "symbols": ["MU"]}],
            }
        ],
    )
    for field in ("one_liner", "row_thesis"):
        text = env.get(field) or ""
        assert "Profits surge" not in text
        assert not is_english_headline(text)
    overview = build_overview_payload(
        watch=[{"symbol": "MU", "name": "Micron", "active": True}],
        events=[],
        briefing={"rows": [{"symbol": "MU", "env_half": env["one_liner"], "row_thesis": env["row_thesis"]}]},
        news=[{"symbol": "MU", "headline": "Profits surge to record high", "themes": ["semis"], "summary": "出口限制缓和"}],
    )
    stock = build_stock_payload(
        symbol="MU",
        watch=[{"symbol": "MU", "active": True}],
        briefing_row={"symbol": "MU", "env_half": env["one_liner"]},
        events=[],
        environment=env,
        env_history=[],
        tape={},
        prediction={"state": "missing", "prediction_ready": False},
        decision={"thesis": {"invalidation": "L0 证据不足", "bull_drivers": [{"text": "prediction_ready=false"}]}},
    )
    review = build_review_payload(
        watch=[{"symbol": "MU"}],
        predictions={"MU": [{"symbol": "MU", "state": "missing", "prediction_ready": False, "thesis": "弱偏多"}]},
        checks={},
    )
    spoken = "\n".join(_spoken(payload) for payload in (overview, stock, review))
    for token in MAIN_PATH_GATE_TOKENS:
        assert token not in spoken, token
    assert "Profits surge" not in spoken
    quote = (stock.get("judge") or {}).get("quote") or ""
    assert not is_english_headline(quote)
    for row in (overview.get("focus") or {}).get("skip") or []:
        assert "Profits surge" not in (row.get("why") or "")
    for card in [overview.get("featured"), *(overview.get("carousel") or [])]:
        if not card:
            continue
        for field in ("title", "conclusion", "horizon"):
            text = card.get(field) or ""
            assert not is_english_headline(text), field
            assert not is_price_like(text), field
            for token in HORIZON_ENUM_TOKENS:
                assert token not in text, f"{field}: {token}"


def test_display_title_keeps_chinese_remainder_of_mixed_headlines() -> None:
    assert display_title("订单超预期：Profits surge to record high") == "订单超预期"
    assert display_title("Profits surge to record high after export curbs ease") == "相关新闻"
    assert display_title("$332.48, +1.81% .") == "相关新闻"
    assert display_title("$332.48, +1.81% .", fallback="$332.48") == "相关新闻"
    mixed = news_card(
        {
            "headline": "订单超预期：Profits surge to record high after export curbs ease",
            "summary": "",
            "themes": ["semis"],
            "symbol": "NVDA",
        },
        [{"symbol": "NVDA", "name": "NVIDIA", "themes": ["semis"], "active": True}],
    )
    assert mixed["title"] == "订单超预期"
    assert "Profits surge" not in mixed["title"]
    assert "Profits surge" in ((mixed.get("basis") or {}).get("source_title") or "")


def test_price_like_only_titles_cannot_be_carousel_primary() -> None:
    assert is_price_like("$332.48, +1.81% .") is True
    assert is_price_like("订单超预期，近端偏多") is False
    assert is_readable_chinese("$332.48, +1.81% .") is False
    assert is_readable_chinese("订单超预期，近端偏多") is True
    watch = [{"symbol": "NVDA", "name": "NVIDIA", "active": True, "themes": ["semis"]}]
    overview = build_overview_payload(
        watch=watch,
        events=[],
        briefing={"rows": []},
        news=[
            {
                "symbol": "NVDA",
                "headline": "$332.48, +1.81% .",
                "summary": "$332.48, +1.81%",
                "themes": ["semis"],
            },
            {
                "symbol": "NVDA",
                "headline": "NVDA 332.48 +1.81%",
                "summary": "+1.81% .",
                "themes": ["semis"],
            },
            {
                "symbol": "NVDA",
                "headline": "$332.48, +1.81% .",
                "summary": "订单超预期，近端偏多",
                "themes": ["semis"],
            },
        ],
    )
    assert overview["featured"] is None
    assert overview["carousel"]
    for card in overview["carousel"]:
        assert carousel_label_ok(card)
        for field in ("title", "conclusion"):
            text = card.get(field) or ""
            assert is_readable_chinese(text), field
            assert not is_price_like(text), field
            assert "$332.48" not in text
            assert "+1.81%" not in text
            assert not is_english_headline(text)
        original = (card.get("basis") or {}).get("source_title") or ""
        assert "$332.48" in original or "332.48" in original
    spoken = " ".join(
        f"{card.get('title') or ''} {card.get('conclusion') or ''}" for card in overview["carousel"]
    )
    assert "订单" in spoken
    price_only = news_card(
        {"headline": "$332.48, +1.81% .", "summary": "+1.81%", "themes": ["semis"], "symbol": "NVDA"},
        watch,
    )
    assert not carousel_label_ok(price_only)
    assert "$332.48" not in (price_only.get("title") or "")
    assert "$332.48" in ((price_only.get("basis") or {}).get("source_title") or "")
    desk = (ROOT / "src/stock_pm/static/desk.js").read_text(encoding="utf-8")
    assert "isPriceLike" in desk
    assert "isReadableChinese" in desk


def test_carousel_and_featured_titles_are_chinese_not_english_walls() -> None:
    overview = build_overview_payload(
        watch=[{"symbol": "NVDA", "name": "NVIDIA", "active": True, "themes": ["semis"]}],
        events=[],
        briefing={"rows": []},
        news=[
            {
                "symbol": "NVDA",
                "headline": "Profits surge to record high after export curbs ease",
                "themes": ["semis"],
                "summary": "订单超预期，近端偏多",
            }
        ],
    )
    assert overview["featured"] is None
    for card in overview["carousel"]:
        assert not is_english_headline(card.get("title") or "")
        assert not is_english_headline(card.get("conclusion") or "")
        assert "Profits surge" not in (card.get("title") or "")
        assert "Profits surge" not in (card.get("conclusion") or "")
        assert "record high" not in (card.get("title") or "")
        original = ((card.get("basis") or {}).get("source_title") or (card.get("basis") or {}).get("fact") or "")
        assert "Profits surge" in original
    news = news_card(
        {
            "headline": "AVGO and MSFT mentioned while NVDA reports orders",
            "summary": "设备订单超预期",
            "themes": ["semis"],
            "symbol": "NVDA",
        },
        [{"symbol": "NVDA", "name": "NVIDIA", "themes": ["semis"], "active": True}],
    )
    assert "reports orders" not in (news.get("title") or "")
    assert not is_english_headline(news.get("title") or "")
    assert "设备订单" in (news.get("title") or "") or "设备订单" in (news.get("conclusion") or "")
    assert "reports orders" in ((news.get("basis") or {}).get("source_title") or (news.get("basis") or {}).get("fact") or "")


def test_featured_horizon_never_speaks_snake_case_enums() -> None:
    assert horizon_label("days_to_weeks") == "数天到数周"
    assert horizon_label("weeks_to_months") == "数周到数月"
    assert horizon_label("until_next_earnings") == "至下份财报"
    assert horizon_label("session_to_days") == "当日到数日"
    assert horizon_label("方向 withheld · 期限 days_to_weeks") == "数天到数周"
    assert "_" not in horizon_label("intra_session_spike")
    card = event_card(
        {
            "canonical_title": "EIA reports crude inventory build after export curbs ease",
            "duration": "days_to_weeks",
            "analysis": {
                "withheld": {"status": "observable"},
                "closed_loop": True,
                "answers": {
                    "what_happened": "EIA reports crude inventory build after export curbs ease",
                    "how_long": "days_to_weeks",
                },
                "horizon": {"text": "days_to_weeks"},
                "causal_chain": {
                    "layers": [
                        {
                            "id": "expectation",
                            "text": "方向 pressure · 期限 days_to_weeks",
                            "horizon": "days_to_weeks",
                        }
                    ]
                },
            },
        },
        [{"symbol": "XOM", "name": "Exxon", "themes": ["energy", "oil_producer"], "active": True}],
    )
    assert card["horizon"] == "数天到数周"
    for token in HORIZON_ENUM_TOKENS:
        assert token not in (card.get("horizon") or "")
        assert token not in (card.get("title") or "")
        assert token not in (card.get("conclusion") or "")
    assert not is_english_headline(card.get("title") or "")
    assert not is_english_headline(card.get("conclusion") or "")
    assert "reports crude" not in (card.get("title") or "")
    assert "inventory build" not in (card.get("conclusion") or "")
    original = (card.get("basis") or {}).get("source_title") or ""
    assert "EIA reports" in original


def test_diagnostic_only_paths_are_explicitly_ungated() -> None:
    missing = [path for path in DIAGNOSTIC_ONLY if not path.exists()]
    assert missing == []
    diag = (ROOT / "src/stock_pm/static/stock_diag.js").read_text(encoding="utf-8")
    assert "L0" in diag or "can_form_direction" in diag
    main = (ROOT / "src/stock_pm/static/stock.js").read_text(encoding="utf-8")
    assert "L0" not in main
    assert "can_form" not in main
    assert "当前可用等级" not in main
    assert "数据源" not in main
    assert (ROOT / "src/stock_pm/static/stock.js") not in DIAGNOSTIC_ONLY
