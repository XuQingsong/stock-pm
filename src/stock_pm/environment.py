"""Knife 2 / Slice B: structured EnvironmentSnapshot for one watchlist symbol.

Pure module (no database). Callers assemble inputs; this file only synthesizes
conclusions, field-level missingFlags, and publishState. It does not invent
year-move, beats, industry phase, valuation, news bias, or atmosphere.
"""

from __future__ import annotations

from typing import Any

from .analytics import _number
from .impact import THEME_NAMES

PUBLISH_STATES = ("published", "draft", "stale", "missing")
ATMOSPHERES = ("恐慌", "承压", "冷淡", "补涨", "过热", "观察")

MACRO_THEMES = frozenset({"rates", "geopolitics"})
SECTOR_THEMES = frozenset(
    {"semis", "consumer_electronics", "telecom", "high_valuation_growth", "index", "gold"}
)

SYMBOL_FIELD_FLAGS = (
    "fundamentals.year_move",
    "fundamentals.earnings",
    "fundamentals.industry",
    "fundamentals.valuation",
    "news.macro",
    "news.sector",
    "news.company",
    "sentiment",
)

FLAG_LABELS = {
    "options": "期权概览",
    "macro": "宏观",
    "reviews": "复盘",
    "environment": "环境半句",
    "fundamentals.year_move": "一年涨跌",
    "fundamentals.earnings": "财报对照",
    "fundamentals.industry": "行业增长",
    "fundamentals.valuation": "估值",
    "news.macro": "宏观消息",
    "news.sector": "行业消息",
    "news.company": "公司消息",
    "sentiment": "情绪氛围",
}


def flag_labels(flags: list[str]) -> str:
    return "、".join(FLAG_LABELS.get(flag, flag) for flag in flags)


def tape_stance(health: str | None, breakout: str | None = None) -> str | None:
    health = (health or "").strip()
    breakout = (breakout or "").strip()
    if health == "走坏" or "跌破" in breakout:
        return "bear"
    if health == "趋势健康" or ("突破" in breakout and "跌" not in breakout and "失败" not in breakout):
        return "bull"
    if health == "过热":
        return "hot"
    if health or breakout:
        return "watch"
    return None


def news_stance(directions: list[str] | None) -> str | None:
    dirs = [str(item) for item in (directions or []) if item]
    bull = any("多" in item for item in dirs)
    bear = any("空" in item for item in dirs)
    if bull and bear:
        return "mixed"
    if bull:
        return "bull"
    if bear:
        return "bear"
    return None


def conclusion_from_stances(tape: str | None, news: str | None) -> str:
    """Environment conclusion only. Never a prediction bound or face-slap rewrite."""
    if tape is None and news is None:
        return "盘面与消息都不足，当前判断置信度有限。"
    if tape is None:
        return "盘面信息不足，当前判断主要依据消息，置信度有限。"
    if news is None:
        return "消息不足，当前判断主要依据盘面。"
    if news == "mixed":
        return "消息内部分歧，当前先按盘面读。"
    if (tape == "bear" and news == "bull") or (tape == "bull" and news == "bear"):
        return "盘面与消息方向相反，当前先以收盘盘面为准。"
    if tape == "hot" and news == "bull":
        return "盘面过热而消息仍偏多，当前按过热处理，暂不提高置信度。"
    return "盘面与消息同向，当前仅作为背景信息，不改变现有判断。"


def _as_clause(text: str | None, fallback: str) -> str:
    """Keep fragments from stealing the A-line 因此 / ending the sentence early."""
    cleaned = (text or "").strip()
    if not cleaned:
        return fallback
    cleaned = cleaned.replace("，因此", "，").replace("因此", "")
    cleaned = cleaned.replace("。", "").rstrip("； ")
    return " ".join(cleaned.split()) or fallback


def causal_one_liner(
    tape_text: str | None,
    news_text: str | None,
    tape: str | None,
    news: str | None,
    *,
    missing_note: str | None = None,
) -> str:
    """A-line: 盘面 → 消息 → 因此. Not juxtaposed slogans."""
    tape_disp = _as_clause(tape_text, "结论不足")
    news_disp = _as_clause(news_text, "暂未形成对该股的明确影响")
    text = (
        f"盘面：{tape_disp}；"
        f"消息：{news_disp}；"
        f"因此：{conclusion_from_stances(tape, news)}"
    )
    if missing_note:
        text += f"{missing_note}不足，暂不提高置信度。"
    return text


def is_conflict_sentence(text: str | None) -> bool:
    raw = text or ""
    return "方向相反" in raw or "不当成两套并列结论" in raw


def is_causal_chain(text: str | None) -> bool:
    """True when A-line is one 盘面→消息→因此 sentence, not two pretty halves."""
    if not text:
        return False
    if "可能相关" in text:
        return False
    i_tape = text.find("盘面")
    i_news = text.find("消息")
    i_so = text.find("因此")
    if min(i_tape, i_news, i_so) < 0 or not (i_tape < i_news < i_so):
        return False
    first_stop = text.find("。")
    if first_stop != -1 and first_stop < i_so:
        return False
    return True


def snapshot_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    flags = row.get("missing_flags")
    if flags is None:
        flags = row.get("missingFlags") or []
    as_of = row.get("as_of_date")
    created = row.get("created_at")
    struct = row.get("struct") or {}
    return {
        "id": row.get("id"),
        "as_of_date": str(as_of)[:10] if as_of else None,
        "scope": row.get("scope") or "symbol",
        "symbol": row.get("symbol"),
        "one_liner": row.get("one_liner"),
        "row_thesis": row.get("row_thesis"),
        "synthesis": (struct.get("synthesis") if isinstance(struct, dict) else None)
        or row.get("one_liner"),
        "struct": struct,
        "missingFlags": list(flags),
        "publishState": row.get("publish_state") or row.get("publishState") or "draft",
        "prediction_ready": False,
        "conflict": bool(struct.get("conflict")) if isinstance(struct, dict) else False,
        "created_at": str(created) if created else None,
        "source": "stored",
    }


def failed_snapshot(
    symbol: str | None,
    as_of_date: str | None,
    error: str,
    *,
    scope: str | None = None,
) -> dict:
    """Visible missing state after a job/input failure. No fabricated numbers."""
    normalized = symbol.upper() if symbol else None
    resolved_scope = scope or ("symbol" if normalized else "market")
    line = "环境信息暂缺，当前判断置信度有限。"
    flags = list(SYMBOL_FIELD_FLAGS) if resolved_scope == "symbol" else ["environment"]
    return {
        "as_of_date": as_of_date,
        "scope": resolved_scope,
        "symbol": normalized,
        "one_liner": line,
        "row_thesis": line,
        "synthesis": line,
        "struct": {
            "fundamentals": None,
            "news": {"macro": None, "sector": None, "company": None},
            "sentiment": None,
            "synthesis": line,
            "conflict": False,
            "error": error,
        },
        "missingFlags": flags,
        "publishState": "missing",
        "prediction_ready": False,
        "conflict": False,
        "source": "failed",
    }


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _year_move(thesis: dict | None, technical: dict | None) -> tuple[dict | None, bool]:
    value = _number((thesis or {}).get("return_1y_pct"))
    if value is None:
        value = _number((technical or {}).get("return_1y_pct"))
    if value is None:
        return None, True
    word = "涨" if value >= 0 else "跌"
    return {
        "return_1y_pct": value,
        "clause": f"过去一年约{word} {abs(value):.1f}%",
    }, False


def _earnings(thesis: dict | None) -> tuple[dict | None, bool]:
    card = dict((thesis or {}).get("earnings_year") or {})
    growth = (thesis or {}).get("growth") or {}
    eps_scored = int(card.get("eps_scored") or 0)
    rev_scored = int(card.get("revenue_scored") or 0)
    if eps_scored == 0 and rev_scored == 0:
        return None, True
    bits: list[str] = []
    quarters = int(card.get("quarters") or 0) or max(eps_scored, rev_scored)
    if eps_scored:
        bits.append(f"近{quarters}季 EPS 超预期 {int(card.get('eps_beats') or 0)}/{eps_scored}")
        missing_est = int(card.get("eps_missing_estimate") or 0)
        if missing_est:
            bits.append(f"{missing_est}季缺预期，未假装达标")
    else:
        bits.append("EPS 对照缺预期，不能说持续超预期")
    if rev_scored:
        bits.append(f"营收超预期 {int(card.get('revenue_beats') or 0)}/{rev_scored}")
    else:
        bits.append("营收对照缺预期，未编达标")
    yoy = _number(growth.get("revenue_yoy_pct"))
    phase = growth.get("phase")
    if yoy is not None and phase in {"放缓", "转负"}:
        bits.append(f"营收同比 {_pct(yoy)}（{phase}）")
    elif yoy is not None:
        bits.append(f"营收同比 {_pct(yoy)}")
    return {"scorecard": card, "clause": "；".join(bits)}, False


def _industry(thesis: dict | None, watch: dict | None) -> tuple[dict | None, bool]:
    growth = (thesis or {}).get("growth") or {}
    phase = growth.get("phase")
    yoy = _number(growth.get("revenue_yoy_pct"))
    if (phase in (None, "样本不足")) and yoy is None:
        return None, True
    theme = growth.get("peer_theme") or ((watch or {}).get("themes") or [None])[0]
    theme_name = THEME_NAMES.get(theme, theme) if theme else (watch or {}).get("sector")
    bits: list[str] = []
    if theme_name:
        bits.append(f"所属{theme_name}")
    if phase and phase != "样本不足":
        bits.append(f"自身营收阶段{phase}")
    elif yoy is not None:
        bits.append(f"自身营收同比 {_pct(yoy)}，阶段样本不足")
    vs = growth.get("vs_peers")
    median = _number(growth.get("peer_revenue_yoy_median"))
    if vs and vs != "样本不足" and median is not None:
        bits.append(f"{vs}（同主题营收同比中位 {_pct(median)}）")
    if not bits:
        return None, True
    return {
        "phase": None if phase == "样本不足" else phase,
        "theme": theme,
        "theme_name": theme_name,
        "clause": "，".join(bits),
    }, False


def _valuation(thesis: dict | None) -> tuple[dict | None, bool]:
    val = dict((thesis or {}).get("valuation") or {})
    label = val.get("label")
    pe = _number(val.get("pe_current"))
    samples = int(val.get("samples") or 0)
    if label in (None, "数据不足") or pe is None or samples <= 0:
        return None, True
    clause = f"现价相对自身一年 PE 分位{label}"
    percentile = _number(val.get("pe_percentile"))
    if percentile is not None:
        clause += f"（约 {percentile:.0f} 分位，PE {pe:.1f}）"
    clause += f"。依据：{val.get('basis') or '未说明'}，不是编出来的贵贱"
    return {**val, "clause": clause}, False


def _bias_from_impacts(
    impacts: list[dict] | None,
    symbol: str,
    themes: list[str] | None,
) -> str | None:
    symbol_u = symbol.upper()
    theme_set = set(themes or [])
    directions: list[str] = []
    for impact in impacts or []:
        symbols = [str(item).upper() for item in (impact.get("symbols") or [])]
        theme = impact.get("theme")
        if symbol_u in symbols or (theme and theme in theme_set):
            direction = str(impact.get("direction") or "")
            if direction:
                directions.append(direction)
    if not directions:
        return None
    bull = any("多" in item for item in directions)
    bear = any("空" in item for item in directions)
    if bull and bear:
        return "分歧"
    if bull:
        return "利多"
    if bear:
        return "利空"
    return "中性"


def _clause_headline(headline: str | None) -> str | None:
    """Chinese headline only. English titles stay off the thesis/clause chain."""
    from stock_pm.ux_copy import drop_english_headlines, is_english_headline

    text = str(headline or "").strip()
    if not text or is_english_headline(text):
        return None
    return drop_english_headlines(text) or None


def _news_layer(
    *,
    key: str,
    items: list[dict],
    bias: str | None,
    empty_reason: str,
) -> tuple[dict | None, bool]:
    if not items:
        return None, True
    if not bias:
        headline = items[0].get("headline") or items[0].get("name") or items[0].get("narrative")
        zh = _clause_headline(headline)
        return {
            "bias": None,
            "headline": headline,
            "clause": f"{empty_reason}暂未形成对该股的明确影响"
            + (f"（{zh}）" if zh else ""),
        }, True
    headline = items[0].get("headline") or items[0].get("name") or items[0].get("narrative")
    clause = f"{key}偏{bias}"
    zh = _clause_headline(headline)
    if zh:
        clause += f"：{zh}"
    return {
        "bias": bias,
        "headline": headline,
        "count": len(items),
        "clause": clause,
    }, False


def _layer_macro(
    symbol: str,
    themes: list[str],
    impact: dict | None,
    news: list[dict],
) -> tuple[dict | None, bool]:
    from .philosophy import impact_row_thesis

    items: list[dict] = []
    impacts: list[dict] = []
    for event in (impact or {}).get("macro") or []:
        event_impacts = list(event.get("impacts") or [])
        if _bias_from_impacts(event_impacts, symbol, themes) is None:
            continue
        row = dict(event)
        row["headline"] = event.get("row_thesis") or impact_row_thesis(event) or event.get("name")
        items.append(row)
        impacts.extend(event_impacts)
    for article in news:
        article_themes = set(article.get("themes") or [])
        if article_themes & MACRO_THEMES:
            items.append(article)
            impacts.extend(article.get("impacts") or [])
    bias = _bias_from_impacts(impacts, symbol, themes)
    return _news_layer(key="宏观", items=items, bias=bias, empty_reason="宏观事件/利率新闻")


def _layer_sector(
    symbol: str,
    themes: list[str],
    news: list[dict],
    peer_news: list[dict],
) -> tuple[dict | None, bool]:
    wanted = set(themes) & SECTOR_THEMES or SECTOR_THEMES
    items: list[dict] = []
    impacts: list[dict] = []
    for article in list(news) + list(peer_news or []):
        article_themes = set(article.get("themes") or [])
        if not (article_themes & wanted):
            continue
        if article_themes and article_themes.issubset(MACRO_THEMES):
            continue
        items.append(article)
        impacts.extend(article.get("impacts") or [])
    bias = _bias_from_impacts(impacts, symbol, themes)
    return _news_layer(key="行业", items=items, bias=bias, empty_reason="行业新闻")


def _layer_company(symbol: str, themes: list[str], news: list[dict]) -> tuple[dict | None, bool]:
    symbol_u = symbol.upper()
    items: list[dict] = []
    impacts: list[dict] = []
    for article in news:
        if str(article.get("symbol") or "").upper() != symbol_u:
            continue
        article_themes = set(article.get("themes") or [])
        if article_themes and article_themes.issubset(MACRO_THEMES):
            continue
        items.append(article)
        impacts.extend(article.get("impacts") or [])
    bias = _bias_from_impacts(impacts, symbol, themes)
    return _news_layer(key="公司", items=items, bias=bias, empty_reason="公司新闻")


def _atmosphere(technical: dict | None, news_fuse: str | None) -> tuple[dict | None, bool]:
    """Q-B atmosphere from the recent path, not title-emotion scores."""
    tech = technical or {}
    r20 = _number(tech.get("return_20d_pct"))
    r5 = _number(tech.get("return_5d_pct"))
    dist_high = _number(tech.get("distance_52w_high_pct"))
    rsi = _number(tech.get("rsi14"))
    health = (tech.get("health") or "").strip()
    volume_ratio = _number(tech.get("volume_ratio_20d"))
    if r20 is None and r5 is None and rsi is None and not health:
        return None, True

    label = "观察"
    if (r20 is not None and r20 <= -15) or (
        r5 is not None and r5 <= -8 and dist_high is not None and dist_high <= -25
    ):
        label = "恐慌"
    elif health == "过热" or (rsi is not None and rsi >= 75) or (r20 is not None and r20 >= 15):
        label = "过热"
    elif r5 is not None and r5 >= 5 and r20 is not None and r20 < 0:
        label = "补涨"
    elif (r20 is not None and r20 <= -5) or health == "走坏":
        label = "承压"
    elif r20 is not None and abs(r20) < 3 and volume_ratio is not None and volume_ratio < 0.8:
        label = "冷淡"

    path_bits: list[str] = []
    if r20 is not None:
        path_bits.append(f"近20日 {_pct(r20)}")
    if r5 is not None:
        path_bits.append(f"近5日 {_pct(r5)}")
    if health:
        path_bits.append(health)
    path = "，".join(path_bits) if path_bits else "近期路径样本有限"
    clause = f"{path}，氛围偏{label}"
    if news_fuse:
        clause += f"；{news_fuse}是导火索，不把标题情绪当氛围"
    else:
        clause += "。情绪看最近怎么走，不数标题正面词"
    return {
        "atmosphere": label,
        "path": path,
        "clause": clause,
        "method": "path",
    }, False


def _publish_state(
    *,
    missing: list[str],
    has_synthesis: bool,
    session: dict | None,
) -> str:
    if session and session.get("is_trading_day") is False:
        return "stale"
    if not has_synthesis:
        return "missing"
    if len(missing) >= 3:
        return "draft"
    return "published"


def _tape_scan_text(
    *,
    briefing_row: dict | None,
    technical: dict | None,
    year: dict | None,
    sentiment: dict | None,
) -> tuple[str | None, str | None]:
    row = briefing_row or {}
    tech = technical or {}
    health = (row.get("health") or tech.get("health") or "").strip()
    breakout = (row.get("breakout_status") or "").strip()
    tape = (row.get("tape") or row.get("short_trend") or "").strip()
    bits: list[str] = []
    if health:
        bits.append(health)
    if breakout and breakout not in bits:
        bits.append(breakout)
    elif tape and tape not in bits:
        bits.append(tape)
    r20 = _number(tech.get("return_20d_pct") or row.get("return_20d_pct"))
    if r20 is not None:
        bits.append(f"近20日{_pct(r20)}")
    if year and year.get("clause"):
        bits.append(year["clause"])
    if sentiment and sentiment.get("atmosphere"):
        bits.append(f"氛围{sentiment['atmosphere']}")
    return ("，".join(bits) if bits else None), tape_stance(health, breakout)


def _news_scan_text(
    macro: dict | None,
    sector: dict | None,
    company: dict | None,
) -> tuple[str | None, str | None]:
    bits: list[str] = []
    dirs: list[str] = []
    for layer, label in ((macro, "宏观"), (sector, "行业"), (company, "公司")):
        if not layer:
            continue
        bias = layer.get("bias")
        if bias:
            dirs.append(bias)
            bits.append(f"{label}{bias}")
        elif layer.get("clause"):
            bits.append(f"{label}信息暂未形成对该股的明确影响")
    if not bits:
        return None, None
    return "，".join(bits), news_stance(dirs)


def synthesize_symbol_environment(
    *,
    as_of_date: str | None,
    symbol: str,
    watch: dict | None = None,
    thesis: dict | None = None,
    technical: dict | None = None,
    news: list[dict] | None = None,
    peer_news: list[dict] | None = None,
    impact: dict | None = None,
    briefing_row: dict | None = None,
    session: dict | None = None,
    source: str = "live",
) -> dict:
    """Full per-symbol EnvironmentSnapshot for requirements §2 / ACCEPTANCE_M1."""
    symbol_u = symbol.upper()
    watch = watch or {}
    themes = list(watch.get("themes") or [])
    articles = list(news or [])
    peers = list(peer_news or [])
    missing: list[str] = []

    year, year_missing = _year_move(thesis, technical)
    if year_missing:
        missing.append("fundamentals.year_move")
    earnings, earnings_missing = _earnings(thesis)
    if earnings_missing:
        missing.append("fundamentals.earnings")
    industry, industry_missing = _industry(thesis, watch)
    if industry_missing:
        missing.append("fundamentals.industry")
    valuation, valuation_missing = _valuation(thesis)
    if valuation_missing:
        missing.append("fundamentals.valuation")

    macro, macro_missing = _layer_macro(symbol_u, themes, impact, articles)
    if macro_missing:
        missing.append("news.macro")
    sector, sector_missing = _layer_sector(symbol_u, themes, articles, peers)
    if sector_missing:
        missing.append("news.sector")
    company, company_missing = _layer_company(symbol_u, themes, articles)
    if company_missing:
        missing.append("news.company")

    fuse = None
    for layer in (macro, sector, company):
        if layer and layer.get("bias") in {"利多", "利空", "分歧"}:
            fuse = layer.get("clause")
            break
    tech = dict(technical or {})
    if briefing_row:
        tech.setdefault("health", briefing_row.get("health"))
        tech.setdefault("return_5d_pct", briefing_row.get("return_5d_pct"))
        tech.setdefault("return_20d_pct", briefing_row.get("return_20d_pct"))
        tech.setdefault("return_1y_pct", briefing_row.get("return_1y_pct"))
        tech.setdefault("rsi14", briefing_row.get("rsi14"))
        tech.setdefault("volume_ratio_20d", briefing_row.get("volume_ratio_20d"))
        tech.setdefault("distance_52w_high_pct", briefing_row.get("distance_52w_high_pct"))
    sentiment, sentiment_missing = _atmosphere(tech, fuse)
    if sentiment_missing:
        missing.append("sentiment")

    tape_text, tape_st = _tape_scan_text(
        briefing_row=briefing_row,
        technical=tech,
        year=year,
        sentiment=sentiment,
    )
    news_text, news_st = _news_scan_text(macro, sector, company)
    has_synthesis = bool(tape_text or news_text)
    synthesis = causal_one_liner(
        tape_text,
        news_text,
        tape_st,
        news_st,
        missing_note=flag_labels(missing) if missing else None,
    )
    row_thesis = synthesis
    one_liner = synthesis
    conflict = is_conflict_sentence(synthesis)
    if session and session.get("is_trading_day") is False:
        label = session.get("label") or "美股休市"
        synthesis = f"{as_of_date or ''} {label}，今日休市，沿用最近交易日环境作为背景。".strip()
        one_liner = synthesis
        row_thesis = synthesis
        has_synthesis = True
        conflict = False

    publish_state = _publish_state(
        missing=missing, has_synthesis=has_synthesis, session=session
    )
    bullets = []
    for title, block in (
        ("基本面 · 一年涨跌", year),
        ("基本面 · 财报", earnings),
        ("基本面 · 行业", industry),
        ("基本面 · 估值", valuation),
        ("消息面 · 宏观", macro),
        ("消息面 · 行业", sector),
        ("消息面 · 公司", company),
        ("情绪面", sentiment),
    ):
        if block and block.get("clause"):
            bullets.append({"title": title, "clause": block["clause"], "points_to": "A"})
        else:
            key = {
                "基本面 · 一年涨跌": "fundamentals.year_move",
                "基本面 · 财报": "fundamentals.earnings",
                "基本面 · 行业": "fundamentals.industry",
                "基本面 · 估值": "fundamentals.valuation",
                "消息面 · 宏观": "news.macro",
                "消息面 · 行业": "news.sector",
                "消息面 · 公司": "news.company",
                "情绪面": "sentiment",
            }[title]
            bullets.append(
                {
                    "title": title,
                    "clause": f"{FLAG_LABELS[key]}不足，暂不提高置信度",
                    "points_to": "A",
                    "missing": True,
                }
            )

    struct = {
        "fundamentals": {
            "year_move": year,
            "earnings": earnings,
            "industry": industry,
            "valuation": valuation,
        },
        "news": {"macro": macro, "sector": sector, "company": company},
        "sentiment": sentiment,
        "synthesis": synthesis,
        "bullets": bullets,
        "conflict": conflict,
        "session": session or None,
    }
    return {
        "as_of_date": as_of_date,
        "scope": "symbol",
        "symbol": symbol_u,
        "one_liner": one_liner,
        "row_thesis": row_thesis,
        "synthesis": synthesis,
        "struct": struct,
        "missingFlags": missing,
        "publishState": publish_state,
        "prediction_ready": False,
        "conflict": conflict,
        "source": source,
    }
