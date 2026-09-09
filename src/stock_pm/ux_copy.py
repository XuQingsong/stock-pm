"""Trader-facing copy for the live UI path.

Keeps engineering / acceptance jargon off the screen. API fields such as
alert_id stay on the wire for CHANGE-01; they are not user-visible labels.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .environment import FLAG_LABELS as ENV_FLAG_LABELS
from .environment import news_stance

BANNED_ON_SCREEN = (
    "旧口径",
    "新口径",
    "模型结果已入库",
    "打开页面不会重新预测",
    "Prediction 对错",
    "质检门",
    "（M2）",
    "（M3）",
    "须带 alert_id",
    "发布态 published",
    "发布态 missing",
)

PUBLISH_STATE_LABELS = {
    "published": "结论已生成",
    "draft": "草稿待补",
    "stale": "结论已过期",
    "missing": "本条未产出",
}

LEGACY_LABEL = "规则对照"
LEGACY_DISCLAIMER = "规则/模型偏向对照，不是时间窗口或涨跌边界。"
PREDICTION_HIT_LABEL = "窗口边界对错"
CONCLUDED_STAMP = "结论已生成"
TAPE_PLACEHOLDER = "昨盘结论未就绪"
JUDGMENT_CHANGE_HINT = "须严重提醒后改口并写原因"
BARE_MISSING = "缺数"

# Short nouns for 「缺…」 lists. Prefer the PM examples when they exist.
MISSING_NOUNS = {
    "window": "时间窗",
    "support": "下沿",
    "resistance": "上沿",
    "price": "对照行情",
    "entry_price": "入场价",
    "tape": "昨盘",
    "environment": "环境",
    "options": "期权",
    "macro": "宏观",
    "reviews": "复盘",
    "fundamentals.year_move": "一年涨跌",
    "fundamentals.earnings": "财报对照",
    "fundamentals.industry": "行业增长",
    "fundamentals.valuation": "估值",
    "news.macro": "宏观消息",
    "news.sector": "行业消息",
    "news.company": "可映射新闻",
    "sentiment": "情绪氛围",
    "volume_price": "量价形态",
    "chips": "筹码与支撑压力",
    "break": "破位走法",
    "env_link": "对照行情",
    "weak_vs_env": "弱于环境",
    "review_note": "复盘总结",
}

ATTENTION_LABELS = {
    "severe_alert": "严重告警",
    "face_slap": "已打脸",
    "overdue": "到期未产出",
    "named_missing": "缺数点名",
    "env_tape_conflict": "环境与昨盘冲突",
    "weak_vs_env": "弱于环境",
    "rest": "其余",
}

_ASCII_RUN = re.compile(r"[A-Za-z]{4,}")
_ASCII_PAREN = re.compile(r"（[^）]*[A-Za-z]{3,}[^）]*）|\([^)]*[A-Za-z]{3,}[^)]*\)")


def publish_label(state: str | None) -> str:
    if not state:
        return ""
    return PUBLISH_STATE_LABELS.get(str(state), "")


def missing_flag_label(flag: str) -> str:
    noun = MISSING_NOUNS.get(flag) or ENV_FLAG_LABELS.get(flag) or flag
    text = str(noun)
    if text.startswith("缺"):
        return text
    return f"缺{text}"


def named_missing_labels(flags: list[str] | None) -> list[str]:
    seen: list[str] = []
    for flag in flags or []:
        label = missing_flag_label(str(flag))
        if label not in seen:
            seen.append(label)
    return seen


def named_missing_line(
    flags: list[str] | None,
    *,
    fallback: str = "本条未产出",
) -> str:
    """Never a bare「缺数」. Name the missing inputs, then refuse to invent bounds."""
    labels = named_missing_labels(flags)
    if labels:
        return f"{'、'.join(labels)}，未编造时间窗口或涨跌边界。"
    return f"{fallback}，未编造时间窗口或涨跌边界。"


def is_http_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def stance_from_directions(directions: list[str] | None) -> str:
    raw = news_stance(directions)
    if raw == "bull":
        return "利好"
    if raw == "bear":
        return "利空"
    if raw == "mixed":
        return "分歧"
    dirs = [str(item) for item in (directions or []) if item]
    if any("中性" in item for item in dirs) and dirs:
        return "分歧"
    return "分歧"


def _because_from_item(item: dict) -> str:
    impacts = item.get("impacts") or []
    for impact in impacts:
        rationale = (impact.get("rationale") or "").strip()
        if rationale:
            return rationale
        theme = (impact.get("theme_name") or impact.get("theme") or "").strip()
        direction = (impact.get("direction") or "").strip()
        if theme and direction:
            return f"{direction}{theme}"
    summary = (item.get("summary") or "").strip()
    if summary:
        return summary[:80]
    if item.get("sentiment") in {"positive", "negative"}:
        return "标题情绪已标注，规则未写出独立依据"
    return "规则未映射到可核对依据"


def news_stance_line(item: dict | None) -> str:
    item = item or {}
    impacts = item.get("impacts") or []
    directions = [str(impact.get("direction") or "") for impact in impacts]
    if not directions and item.get("sentiment") == "positive":
        directions = ["利多"]
    elif not directions and item.get("sentiment") == "negative":
        directions = ["利空"]
    stance = stance_from_directions(directions)
    return f"{stance} · 因为{_because_from_item(item)}"


def decorate_news_item(item: dict | None) -> dict:
    """Add trader-facing news fields. Never invent a URL."""
    row = item if isinstance(item, dict) else {}
    url = row.get("url")
    has_url = is_http_url(url)
    row["has_url"] = has_url
    row["url"] = str(url).strip() if has_url else None
    row["url_label"] = "原文" if has_url else "无原文链接"
    row["stance_line"] = news_stance_line(row)
    return row


def strip_embedded_headlines(text: str | None) -> str:
    """Drop long English / Latin parentheticals from scan halves."""
    cleaned = _ASCII_PAREN.sub("", text or "")
    return " ".join(cleaned.split())


def env_half_display(env: dict | None, fallback: str | None = None) -> str:
    """Overview 环境半句: Chinese stance, no long English headlines."""
    env = env or {}
    struct = env.get("struct") or {}
    news = struct.get("news") or {}
    news_bits: list[str] = []
    has_article = False
    for key, label in (("macro", "宏观"), ("sector", "行业"), ("company", "公司")):
        layer = news.get(key) or {}
        bias = layer.get("bias")
        if bias in {"利多", "利空", "分歧"}:
            news_bits.append(f"{label}{bias}")
            if layer.get("headline") or layer.get("url"):
                has_article = True
    news_text = "，".join(news_bits) if news_bits else None
    if news_text and has_article:
        news_text += " · 可点新闻"

    one = strip_embedded_headlines(env.get("one_liner") or fallback or "")
    tape_part = None
    so_part = None
    if "盘面：" in one and "；消息：" in one:
        tape_part = one.split("盘面：", 1)[1].split("；消息：", 1)[0].strip()
    if "因此：" in one:
        so_part = one.split("因此：", 1)[1].strip()
    if tape_part and news_text and so_part:
        return f"盘面：{tape_part}；消息：{news_text}；因此：{so_part}"
    if news_text and so_part:
        return f"消息：{news_text}；因此：{so_part}"
    return one or "数据暂缺"


def first_env_news(env: dict | None) -> dict | None:
    struct = (env or {}).get("struct") or {}
    news = struct.get("news") or {}
    for key in ("company", "sector", "macro"):
        layer = news.get(key) or {}
        headline = layer.get("headline")
        if not headline:
            continue
        return decorate_news_item(
            {
                "headline": headline,
                "url": layer.get("url"),
                "impacts": [
                    {
                        "direction": layer.get("bias"),
                        "theme_name": key,
                        "rationale": (layer.get("clause") or "").split("：", 1)[-1],
                    }
                ],
                "summary": layer.get("clause"),
            }
        )
    return None


def attention_rank(row: dict | None) -> dict:
    """Sort key for 总览 / 复盘. Featured first; rest can fold."""
    row = row or {}
    pred = row.get("prediction") or {}
    tape = row.get("tape_analysis") or {}
    env = row.get("environment") or {}
    state = pred.get("state")
    flags = list(pred.get("missingFlags") or [])
    env_flags = list(env.get("missingFlags") or [])
    tape_flags = list(tape.get("missingFlags") or [])
    alert = pred.get("judgment_alert") or {}
    prior = (row.get("prior_outcome") or {}).get("outcome_vs_bias")
    weak = (tape.get("weak_vs_env") or {}).get("status")
    conflict = bool(row.get("env_tape_conflict") or tape.get("conflict") or env.get("conflict"))

    key = "rest"
    if alert.get("id") and alert.get("severity") == "severe":
        key = "severe_alert"
    elif state == "invalidated" or prior == "相反":
        key = "face_slap"
    elif state == "missing" and not flags:
        key = "overdue"
    elif flags or (
        (not pred.get("prediction_ready")) and (env_flags or tape_flags or flags)
    ):
        key = "named_missing"
    elif env_flags and (env.get("publishState") in {"missing", "draft"}):
        key = "named_missing"
    elif conflict:
        key = "env_tape_conflict"
    elif weak == "weak":
        key = "weak_vs_env"

    rank = {
        "severe_alert": 0,
        "face_slap": 1,
        "overdue": 2,
        "named_missing": 3,
        "env_tape_conflict": 4,
        "weak_vs_env": 5,
        "rest": 6,
    }[key]
    return {
        "rank": rank,
        "key": key,
        "label": ATTENTION_LABELS[key],
        "featured": rank <= 5,
        "tone": {
            "severe_alert": "severe",
            "face_slap": "slap",
            "overdue": "overdue",
            "named_missing": "missing",
            "env_tape_conflict": "conflict",
            "weak_vs_env": "weak",
            "rest": "rest",
        }[key],
    }


def annotate_attention(row: dict) -> dict:
    payload = dict(row)
    payload["attention"] = attention_rank(payload)
    return payload


def sort_attention_rows(rows: list[dict]) -> list[dict]:
    annotated = [annotate_attention(row) for row in rows]
    annotated.sort(key=lambda row: (row["attention"]["rank"], str(row.get("symbol") or "")))
    return annotated


def featured_and_rest(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered = sort_attention_rows(rows)
    featured = [row for row in ordered if row["attention"]["featured"]]
    rest = [row for row in ordered if not row["attention"]["featured"]]
    return featured, rest


def ui_copy_violations(text: str) -> list[str]:
    return [phrase for phrase in BANNED_ON_SCREEN if phrase in (text or "")]
