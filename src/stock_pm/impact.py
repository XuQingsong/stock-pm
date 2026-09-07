from __future__ import annotations

"""Theme taxonomy, news tagging, and macro-event impact mapping.

Rule-based on purpose: only pre-defined event types and themes are
recognized. Anything the rules cannot classify stays untagged instead of
being force-fitted.
"""

from typing import Any


THEME_NAMES: dict[str, str] = {
    "rates": "利率/通胀",
    "high_valuation_growth": "高估值成长",
    "semis": "半导体/AI",
    "consumer_electronics": "消费电子",
    "telecom": "通信设备",
    "index": "指数ETF",
    "gold": "黄金",
    "geopolitics": "地缘/关税",
}

NEWS_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rates": (
        "fed", "federal reserve", "rate cut", "rate hike", "interest rate",
        "inflation", "cpi", "pce", "payroll", "nonfarm", "jobs report",
        "treasury", "yield", "fomc", "powell",
    ),
    "semis": (
        "chip", "semiconductor", " ai ", "artificial intelligence", "gpu",
        "foundry", "hbm", "data center", "datacenter", "nvidia", "broadcom",
        "micron", "intel", "hynix", "tsmc", "memory price",
    ),
    "consumer_electronics": (
        "iphone", "smartphone", "apple", "consumer electronics", "pc shipment",
        "handset",
    ),
    "telecom": ("5g", "network equipment", "nokia", "ericsson", "telecom"),
    "geopolitics": (
        "tariff", "export control", "export ban", "sanction", "geopolit",
        "trade war",
    ),
}

POSITIVE_WORDS = (
    "beat", "surge", "rise", "growth", "record", "upgrade", "rally",
    "tops estimate", "raises guidance",
)
NEGATIVE_WORDS = (
    "miss", "fall", "drop", "cut", "risk", "downgrade", "plunge", "layoff",
    "probe", "lowers guidance", "recall",
)


def tag_news(text: str) -> list[str]:
    """Return the ordered list of themes whose keywords appear in the text."""
    lowered = f" {(text or '').lower()} "
    return [
        theme
        for theme, keywords in NEWS_THEME_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]


def news_sentiment(text: str) -> str:
    lowered = (text or "").lower()
    positive = sum(word in lowered for word in POSITIVE_WORDS)
    negative = sum(word in lowered for word in NEGATIVE_WORDS)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


# (event_type, surprise) -> narrative and per-theme direction.
# Direction is from the perspective of the theme's holdings.
MACRO_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("nfp", "below"): {
        "narrative": "非农弱于预期 → 降息预期升温",
        "impacts": [
            ("high_valuation_growth", "利多", "贴现率预期下行，高估值成长受益"),
            ("gold", "利多", "实际利率预期下行"),
            ("index", "利多", "流动性预期改善"),
        ],
    },
    ("nfp", "above"): {
        "narrative": "非农强于预期 → 降息预期降温",
        "impacts": [
            ("high_valuation_growth", "利空", "贴现率预期上行压制估值"),
            ("gold", "利空", "实际利率预期上行"),
            ("index", "偏空", "流动性预期收紧"),
        ],
    },
    ("cpi", "above"): {
        "narrative": "CPI 高于预期 → 通胀压力，加息/维持高利率预期升温",
        "impacts": [
            ("high_valuation_growth", "利空", "利率预期上行压制估值"),
            ("gold", "中性偏多", "通胀对冲需求 vs 利率压制，方向不定"),
            ("index", "利空", "折现率与风险偏好双重压制"),
        ],
    },
    ("cpi", "below"): {
        "narrative": "CPI 低于预期 → 通胀降温，降息预期升温",
        "impacts": [
            ("high_valuation_growth", "利多", "利率预期下行利于估值扩张"),
            ("gold", "利多", "实际利率预期下行"),
            ("index", "利多", "风险偏好改善"),
        ],
    },
    ("pce", "above"): {
        "narrative": "核心 PCE 高于预期 → 联储偏鹰概率上升",
        "impacts": [
            ("high_valuation_growth", "利空", "利率预期上行"),
            ("index", "偏空", "风险偏好承压"),
        ],
    },
    ("pce", "below"): {
        "narrative": "核心 PCE 低于预期 → 联储转鸽空间加大",
        "impacts": [
            ("high_valuation_growth", "利多", "利率预期下行"),
            ("index", "利多", "风险偏好改善"),
        ],
    },
    ("fomc", "cut"): {
        "narrative": "FOMC 降息",
        "impacts": [
            ("high_valuation_growth", "利多", "融资成本与贴现率下行"),
            ("gold", "利多", "实际利率下行"),
            ("index", "利多", "流动性宽松"),
        ],
    },
    ("fomc", "hike"): {
        "narrative": "FOMC 加息",
        "impacts": [
            ("high_valuation_growth", "利空", "贴现率上行"),
            ("gold", "利空", "持有成本上升"),
            ("index", "利空", "流动性收紧"),
        ],
    },
    ("fomc", "hold"): {
        "narrative": "FOMC 按兵不动，关注点在声明与点阵图",
        "impacts": [
            ("index", "中性", "方向取决于指引，事件本身中性"),
        ],
    },
}


def _impact_row(
    theme: str,
    direction: str,
    rationale: str,
    theme_symbols: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "theme": theme,
        "theme_name": THEME_NAMES.get(theme, theme),
        "direction": direction,
        "rationale": rationale,
        "symbols": theme_symbols.get(theme, []),
    }


EASING_HINTS = (
    "rate cut", "cuts rates", "dovish", "cooling inflation", "inflation cools",
    "weaker jobs", "jobs miss", "payrolls miss", "below forecast", "softer cpi",
    "pce cools", "unemployment rises", "trims rates",
)
TIGHTENING_HINTS = (
    "rate hike", "hikes rates", "hawkish", "hot inflation", "inflation jumps",
    "strong jobs", "payrolls beat", "above forecast", "hotter cpi",
    "sticky inflation", "holds rates high",
)


def _rates_tilt(text: str) -> str | None:
    lowered = (text or "").lower()
    easing = sum(hint in lowered for hint in EASING_HINTS)
    tightening = sum(hint in lowered for hint in TIGHTENING_HINTS)
    if easing > tightening:
        return "easing"
    if tightening > easing:
        return "tightening"
    return None


def news_impacts(article: dict, theme_symbols: dict[str, list[str]]) -> list[dict]:
    """Map one tagged article to watchlist themes. Untagged articles return []."""
    text = f"{article.get('headline') or ''} {article.get('summary') or ''}"
    themes = list(article.get("themes") or [])
    if not themes:
        return []
    results: list[dict] = []
    seen: set[str] = set()
    if "rates" in themes:
        tilt = _rates_tilt(text)
        if tilt == "easing":
            mapped = [
                ("high_valuation_growth", "利多", "利率新闻偏向宽松/降息预期"),
                ("gold", "利多", "实际利率预期下行"),
                ("index", "利多", "流动性预期改善"),
            ]
        elif tilt == "tightening":
            mapped = [
                ("high_valuation_growth", "利空", "利率新闻偏向收紧/加息预期"),
                ("gold", "利空", "实际利率预期上行"),
                ("index", "偏空", "流动性预期收紧"),
            ]
        else:
            mapped = [
                ("high_valuation_growth", "中性", "命中利率主题，但标题无法判断宽松或收紧"),
            ]
        for theme, direction, rationale in mapped:
            seen.add(theme)
            results.append(_impact_row(theme, direction, rationale, theme_symbols))
        seen.add("rates")
    sentiment = article.get("sentiment") or "neutral"
    sentiment_dir = {"positive": "利多", "negative": "利空"}.get(sentiment, "中性")
    for theme in themes:
        if theme in seen:
            continue
        seen.add(theme)
        results.append(
            _impact_row(
                theme,
                sentiment_dir,
                f"命中「{THEME_NAMES.get(theme, theme)}」关键词，情绪为{sentiment}（规则标注，不是因果）",
                theme_symbols,
            )
        )
    return results


def macro_impact(event: dict, theme_symbols: dict[str, list[str]]) -> dict | None:
    """Map one macro event row to the affected watchlist symbols.

    Returns None when the (event_type, surprise) pair has no rule — the
    caller should show the raw event without pretending to know its impact.
    """
    rule = MACRO_RULES.get((event["event_type"], event["surprise"]))
    if not rule:
        return None
    impacts = []
    for theme, direction, rationale in rule["impacts"]:
        impacts.append(
            {
                "theme": theme,
                "theme_name": THEME_NAMES.get(theme, theme),
                "direction": direction,
                "rationale": rationale,
                "symbols": theme_symbols.get(theme, []),
            }
        )
    return {
        "event_type": event["event_type"],
        "event_time": event["event_time"],
        "name": event["name"],
        "actual": event.get("actual"),
        "consensus": event.get("consensus"),
        "unit": event.get("unit"),
        "surprise": event["surprise"],
        "narrative": rule["narrative"],
        "impacts": impacts,
    }
