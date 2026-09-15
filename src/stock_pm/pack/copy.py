"""Investor-facing copy for the frozen decision-system pages.

Main path only says: conclusion · reason · action.
System self-justification stays in diagnostic / settings / expand-evidence.
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

# Permanent CI gate (templates + helper output). Wire keys may still exist
# in Python logic; they must not appear as main-path UI copy.
MAIN_PATH_GATE_TOKENS = (
    "不编",
    "不补",
    "禁止",
    "closed loop",
    "closed_loop",
    "prediction_ready",
    "evidence version",
    "evidence_version",
    "can_form",
    "API未配置",
    "API 未配置",
    "抓取失败",
    "L0",
)
MAIN_PATH_BANNED = (
    "不补假数",
    "不编方向",
    "不写成预测或打脸",
    "不写成预测",
    "不静默判对",
    "禁止进校验",
    "禁止",
    "字段齐全",
    "标题扫代码",
    "数据源健康",
    "API 未配置",
    "API未配置",
    "抓取失败",
    "抓取",
    "evidence version",
    "closed loop",
    "can_form_direction",
    "prediction_ready",
    "source tier",
    "rule v0",
    "rule_id",
    "本页不出现",
    "本页不展开",
    "未编造",
    "未编",
    "不编造",
    "不编",
    "不补",
    "不硬编",
    "编出来",
    "不形成方向",
    "withheld",
    "L0",
    "L1",
    "L2",
    "L3",
    "system-risk",
    "system_risk",
    "risk_state",
    "chain_id",
    "synthesis_id",
)

_SKIP_SCRUB_KEYS = {
    "alert_id",
    "prediction_id",
    "event_id",
    "id",
    "href",
    "url",
    "diagnostics",
    "basis",
    "closed_loop",
    "can_form_direction",
    "prediction_ready",
    "source_kind",
    "event_type",
    "symbol",
}

# Longer phrases first. System-rule language → investment meaning.
_PHRASE_REWRITES: tuple[tuple[str, str], ...] = (
    ("只作环境理解，不写成预测或打脸。", "当前仅作为背景信息，不改变现有判断。"),
    ("只作环境理解，不写成预测或打脸", "当前仅作为背景信息，不改变现有判断"),
    ("宏观有标题未映射，不编方向", "宏观信息暂未形成对该股的明确影响"),
    ("行业有标题未映射，不编方向", "行业信息暂未形成对该股的明确影响"),
    ("公司有标题未映射，不编方向", "公司信息暂未形成对该股的明确影响"),
    ("有标题未映射，不编方向", "暂未形成对该股的明确影响"),
    ("暂缺，不编方向", "暂未形成对该股的明确影响"),
    ("判断暂缺，不编方向", "判断暂缺，维持观察"),
    ("不编结论，也不编预测。", "当前判断置信度有限。"),
    ("不编结论，也不编预测", "当前判断置信度有限"),
    ("也不编预测。", "置信度有限。"),
    ("也不编预测", "置信度有限"),
    ("不编影响，也不编预测。", "当前判断主要依据盘面。"),
    ("不编影响，也不编预测", "当前判断主要依据盘面"),
    ("不把消息标题当成盘面结论，也不编预测。", "当前判断主要依据消息，置信度有限。"),
    ("不把利多加成预测。", "暂不提高置信度。"),
    ("不把标题墙当成两套结论。", "先按盘面读。"),
    ("不当成两套并列结论。", "当前先以收盘盘面为准。"),
    ("缺口：", ""),
    ("，不补假数。", "不足，当前判断置信度有限。"),
    ("不补假数。", "当前判断置信度有限。"),
    ("不补假数", "当前判断置信度有限"),
    ("对照行情暂缺，不静默判对", "对照行情暂缺，暂不判定对错"),
    ("对照价缺失，不静默判对", "对照价格暂缺，暂不判定对错"),
    ("禁止进校验主口径", "不计入预测准确率"),
    ("字段齐全、可进校验的正式预测", "可验证的正式预测"),
    ("字段齐全才可进校验", "可验证后才计入准确率"),
    ("未编造时间窗口或涨跌边界。", "当前仅作为观察，不计入预测准确率。"),
    ("未编造时间窗口或涨跌边界", "当前仅作为观察，不计入预测准确率"),
    ("决策未形成方向，不展示百分比预测", "当前条件不足，暂不形成可验证预测"),
    ("无法形成正式预测", "当前条件不足，暂不形成可验证预测"),
    ("证据不足，不形成方向", "当前条件不足，暂不形成明确方向"),
    ("未映射方向，不编影响", "暂未形成对该股的明确影响"),
    ("环境快照生成失败，数据暂缺，未编造数字。", "环境信息暂缺，当前判断置信度有限。"),
    ("昨盘数据暂缺，未编造量价。", "昨盘信息不足，当前判断主要依据消息与环境。"),
    ("复盘总结暂缺，未编造白话。", "复盘总结暂缺，尚不能解释昨天为何这样走。"),
    ("不编造当日盘面。", "沿用最近交易日环境作为背景。"),
    ("不编造当日量价。", "沿用最近交易日盘面作为背景。"),
    ("不编当日预测边界。", "暂不形成当日预测。"),
    ("不编当日因果。", "沿用最近交易日解释作为背景。"),
    ("不是从标题里扫全部代码", "针对这只自选股"),
    ("不是标题点名该代码", "与该股行业主题相关"),
    ("不是把战争标题抄到所有股票", "直接受油价变化影响"),
    ("不是把宏观标题抄到所有股票", "对该股估值有影响"),
    ("不把标题抄到全部标的", "暂未形成对自选股的明确影响"),
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


_TOKEN_RE = re.compile(
    r"\b(?:can_form_direction|prediction_ready|closed_loop|source[_\s-]?tier|rule\s*v0|rule_id|chain_id|synthesis_id|evidence[_\s-]?version|system[-_]risk|risk_state|withheld)\b(?:\s*=\s*\S+)?",
    re.I,
)
_LEVEL_RE = re.compile(r"未达\s*L3|\bL[0-3]\b")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[。！？；;])")
_RESIDUE_RE = re.compile(
    r"不编|不补|未编|禁止|抓取|字段齐全|本页不出现|本页不展开|标题扫代码|数据源健康|"
    r"API\s*未配置|closed[\s_-]*loop|prediction_ready|can_form_direction|"
    r"evidence[\s_-]*version|rule\s*v0|rule_id|chain_id|synthesis_id|"
    r"system[-_]risk|risk_state|\bL[0-3]\b|withheld|不形成方向|不静默|"
    r"不写成预测|编出来|不硬编",
    re.I,
)


def main_path_violations(text: str | None) -> list[str]:
    raw = text or ""
    hits = [phrase for phrase in MAIN_PATH_BANNED if phrase in raw]
    for match in _RESIDUE_RE.findall(raw):
        token = match if isinstance(match, str) else match[0]
        if token and token not in hits:
            hits.append(token)
    return hits


def _drop_banned_clauses(text: str) -> str:
    """Delete leftover system/acceptance clauses instead of softening them."""
    if not text:
        return ""
    kept: list[str] = []
    for chunk in _CLAUSE_SPLIT_RE.split(text):
        if not chunk.strip():
            continue
        if main_path_violations(chunk) or _TOKEN_RE.search(chunk) or _LEVEL_RE.search(chunk):
            continue
        kept.append(chunk)
    return "".join(kept)


def investorize(text: str | None) -> str:
    """Last-line defense: rewrite known leftovers, then drop banned residue."""
    raw = str(text or "")
    for old, new in _PHRASE_REWRITES:
        raw = raw.replace(old, new)
    raw = raw.replace("风险状态", "市场波动风险")
    from stock_pm.ux_copy import drop_english_headlines

    raw = drop_english_headlines(raw)
    raw = _drop_banned_clauses(raw)
    raw = _TOKEN_RE.sub("", raw)
    raw = _LEVEL_RE.sub("", raw)
    return " ".join(raw.split())


def main_path_copy(text: str | None, *, fallback: str = "") -> str:
    cleaned = investorize(strip_holdings(text))
    return cleaned or fallback


def judgment_reason(text: str | None, *, fallback: str = "依据暂缺，维持观察") -> str:
    """One reason sentence. Drops 盘面/消息 scaffolding and 缺口 dumps."""
    raw = main_path_copy(text)
    if "因此：" in raw:
        raw = raw.split("因此：", 1)[1]
    elif "因此" in raw:
        raw = raw.split("因此", 1)[1].lstrip("：: ")
    for marker in ("缺口：", "缺："):
        if marker in raw:
            raw = raw.split(marker, 1)[0]
    for sep in ("。", "；"):
        if sep in raw:
            head = raw.split(sep, 1)[0].strip()
            if head:
                raw = head
                break
    raw = raw.strip(" ；。")
    return raw[:120] if raw else fallback


def judgment_headline(text: str | None, *, fallback: str) -> str:
    """Short yesterday/today line: conclusion, not a tape+news dump."""
    raw = main_path_copy(text)
    if not raw:
        return fallback
    if "盘面：" in raw or "消息：" in raw:
        return judgment_reason(raw, fallback=fallback)
    return raw[:80]


def missing_consequence(flags: list[str] | None, *, fallback: str = "当前判断置信度有限") -> str:
    """Missing data as a decision consequence, not a tech dump."""
    from stock_pm.ux_copy import named_missing_labels

    labels = named_missing_labels(flags)
    nouns = [item[1:] if item.startswith("缺") else item for item in labels]
    if not nouns:
        return fallback
    joined = "、".join(nouns)
    if any(key in joined for key in ("估值",)):
        return f"{joined}不足，暂不提高置信度"
    if any(key in joined for key in ("宏观",)):
        return f"{joined}不足，当前判断主要依据公司与行业"
    if any(key in joined for key in ("新闻", "消息")):
        return f"{joined}不足，暂未形成对自选股的明确影响"
    if any(key in joined for key in ("时间窗", "上沿", "下沿", "对照")):
        return f"{joined}不足，当前仅作为观察，不计入预测准确率"
    return f"{joined}不足，当前判断置信度有限"


def scrub_visible(value: Any, *, key: str | None = None) -> Any:
    """Last-line defense: investorize string leaves in a packed payload."""
    if key in _SKIP_SCRUB_KEYS:
        return value
    if isinstance(value, str):
        return investorize(value)
    if isinstance(value, list):
        return [scrub_visible(item) for item in value]
    if isinstance(value, dict):
        return {inner: scrub_visible(item, key=inner) for inner, item in value.items()}
    return value


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
