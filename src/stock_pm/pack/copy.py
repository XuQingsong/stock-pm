"""Trader-facing copy for the frozen decision-system pages.

No portfolio/position verbs on the main path. No A/B/C, R-codes, L0,
PredictionCheck, v0, or re-eval queue as primary labels.
"""

from __future__ import annotations

import re
from typing import Any

HOLDINGS_BANNED = (
    "减仓",
    "加仓",
    "清仓",
    "建仓",
    "有仓",
    "持有仓",
    "仓位动作",
    "买入建议",
    "卖出建议",
)

JARGON_BANNED_PRIMARY = (
    "A层",
    "B层",
    "C层",
    "L0",
    "L3",
    "PredictionCheck",
    "重评队列",
    "R-0",
    "v0",
)

_HOLDINGS_RE = re.compile("|".join(re.escape(item) for item in HOLDINGS_BANNED))

SCOPE_LABELS = {
    "company": "公司级",
    "company_filing": "公司级",
    "company_earnings": "公司级",
    "industry": "行业级",
    "sector": "行业级",
    "market": "市场级",
    "macro": "宏观",
    "global": "宏观",
}

HORIZON_LABELS = {
    "days_to_weeks": "数日至数周",
    "weeks_to_months": "1–4 周",
    "until_next_earnings": "至下份财报",
    "unspecified": "期限暂缺",
}

DIRECTION_LABELS = {
    "bull": "偏多",
    "bear": "偏空",
    "mixed": "分歧",
    "none": "观望",
    "pressure": "偏空",
    "relief": "偏多",
    "watch": "留意",
    "bullish": "偏多",
    "bearish": "偏空",
}

NEAR_STATE = {
    "bull_direct": "近端弹性上修",
    "bull": "研究倾向偏多",
    "bear_direct": "近端转谨慎",
    "bear": "近端转谨慎",
    "watch": "中性偏多",
    "none": "无新变化",
    "mute": "观望",
}

ACTION_VERBS = {
    "bull": ("研究倾向偏多", "不追高（观察）"),
    "bear": ("近端转谨慎",),
    "watch": ("留意条件",),
    "none": ("观望",),
}


def strip_holdings(text: str | None) -> str:
    raw = str(text or "")
    cleaned = _HOLDINGS_RE.sub("研究倾向", raw)
    return " ".join(cleaned.split())


def scope_label(scope: str | None, event_type: str | None = None) -> str:
    key = str(scope or event_type or "").strip().lower()
    if key in SCOPE_LABELS:
        return SCOPE_LABELS[key]
    if event_type in SCOPE_LABELS:
        return SCOPE_LABELS[event_type]
    if event_type in {"central_bank_rates", "inflation_employment", "vix_risk", "fx_usd"}:
        return "宏观"
    if event_type in {"war_sanctions", "energy_supply", "gold_wti"}:
        return "行业级"
    return "市场级"


def horizon_label(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text or text in {"unspecified", "none", "null"}:
        return HORIZON_LABELS["unspecified"]
    return HORIZON_LABELS.get(text, text.replace("_", " "))


def direction_side(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    if text in {"bull", "bullish", "relief", "利多", "偏多", "positive"}:
        return "bull"
    if text in {"bear", "bearish", "pressure", "利空", "偏空", "negative"}:
        return "bear"
    if text in {"mixed", "watch", "分歧", "中性", "yellow"}:
        return "watch"
    return "none"


def near_state(side: str, *, direct: bool = False) -> str:
    if side == "bull":
        return NEAR_STATE["bull_direct"] if direct else NEAR_STATE["bull"]
    if side == "bear":
        return NEAR_STATE["bear_direct"]
    if side == "watch":
        return NEAR_STATE["watch"]
    return NEAR_STATE["none"]


def action_verbs(side: str) -> tuple[str, ...]:
    return ACTION_VERBS.get(side) or ACTION_VERBS["none"]


def mmdd(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[5:7]}-{text[8:10]}"
    return text[:10] or "—"


def named_gap(flags: list[str] | None) -> str | None:
    if not flags:
        return None
    from stock_pm.ux_copy import named_missing_labels

    labels = named_missing_labels(flags)
    if not labels:
        return None
    return "、".join(labels)


def research_lean(side: str, *, confidence: str | None = None, horizon: str | None = None) -> str:
    bits = [near_state(side) if side != "bull" else "研究倾向偏多"]
    if side == "bull":
        bits = ["研究倾向偏多"]
    elif side == "bear":
        bits = ["近端转谨慎"]
    elif side == "watch":
        bits = ["中性偏多"]
    else:
        bits = ["观望"]
    hz = horizon_label(horizon) if horizon else ""
    if hz and hz != HORIZON_LABELS["unspecified"]:
        bits.append(f"近 {hz}")
    if confidence in {"high", "medium"}:
        bits.append("置信度中高" if confidence == "medium" or confidence == "high" else "")
    return " · ".join(item for item in bits if item)
