"""Permanent main-path copy gate.

Fails CI if overview / stock / review templates or copy-helper output still
contain DEV_BRIEF system/acceptance tokens. Diagnostic-only files (stock.js,
shell.js, events_ui.js, settings) may mention tech terms; they are not gated.
"""

from __future__ import annotations

import ast
from pathlib import Path

from stock_pm.environment import synthesize_symbol_environment
from stock_pm.pack.copy import (
    MAIN_PATH_BANNED,
    MAIN_PATH_GATE_TOKENS,
    investorize,
    judgment_reason,
    main_path_copy,
    main_path_violations,
)
from stock_pm.pack.overview import build_overview_payload
from stock_pm.pack.review_page import build_review_payload
from stock_pm.pack.stock_page import build_stock_payload
from stock_pm.ux_copy import is_english_headline

ROOT = Path(__file__).resolve().parents[1]

# Main investment templates. Every string here can render to the user.
MAIN_PATH_TEMPLATES = (
    ROOT / "src/stock_pm/static/overview.html",
    ROOT / "src/stock_pm/static/stock.html",
    ROOT / "src/stock_pm/static/review.html",
    ROOT / "src/stock_pm/static/desk.js",
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
    ROOT / "src/stock_pm/static/stock.js",
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
        for extra in ("L1", "L2", "L3", "本页不出现", "字段齐全", "不形成方向"):
            assert extra not in text, f"{path.relative_to(ROOT)}: {extra!r}"


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


def test_diagnostic_only_paths_are_explicitly_ungated() -> None:
    missing = [path for path in DIAGNOSTIC_ONLY if not path.exists()]
    assert missing == []
    # Diagnostic fold is allowed to mention tech terms; the gate must not scan it.
    diag = (ROOT / "src/stock_pm/static/stock.js").read_text(encoding="utf-8")
    assert "L0" in diag or "can_form_direction" in diag
