"""Overview view-model: featured event, 今日重点关注, carousel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from stock_pm.calendar import NY_TZ, is_trading_day, session_status

from .cards import build_event_cards, focus_rows


def brand_meta(now: datetime | None = None) -> str:
    current = now or datetime.now(tz=NY_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NY_TZ)
    local = current.astimezone(NY_TZ)
    stamp = f"{local:%m-%d}"
    day = local.date()
    if not is_trading_day(day):
        label = session_status(day).get("label") or "休市"
        return f"{stamp} {label}"
    minutes = local.hour * 60 + local.minute
    if minutes < 9 * 60 + 30:
        phase = "美东盘前"
    elif minutes < 16 * 60:
        phase = "美东盘中"
    else:
        phase = "美东盘后"
    return f"{stamp} {phase}"


def build_overview_payload(
    *,
    watch: list[dict[str, Any]],
    events: list[Any],
    briefing: dict[str, Any] | None,
    now: datetime | None = None,
    coverage: dict[str, Any] | None = None,
    news: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    watch_rows = [row for row in (watch or []) if row.get("active", True)]
    split = build_event_cards(events, watch_rows, news=news)
    featured = split["featured"]
    carousel = split["carousel"]
    unmapped = split["unmapped"]
    all_cards = ([featured] if featured else []) + carousel + unmapped
    focus = focus_rows(watch_rows, list((briefing or {}).get("rows") or []), all_cards)
    empty_focus = not (focus["priority"] or focus["watch"] or focus["skip"])
    return {
        "as_of": (now or datetime.now(tz=NY_TZ)).isoformat(),
        "brand_meta": brand_meta(now),
        "page": {
            "title": "今天什么改变了",
            "sub": "主事件置顶 · 其下「今日重点关注」三行紧凑 · 其余市场事件轮播 · 整行点进个股（无持仓）",
        },
        "featured": featured,
        "featured_missing": None if featured else "今日没有可置顶的主事件。",
        "focus": {
            "lead": "每行：标的｜近端判断 · 一句原因 · 一个观察条件。",
            "priority": focus["priority"],
            "watch": focus["watch"],
            "skip": focus["skip"],
            "skip_count": focus["skip_count"],
            "empty": "自选暂无因新闻需留意的变化。" if empty_focus else None,
        },
        "carousel": carousel,
        "unmapped": [
            {
                "title": card.get("title"),
                "note": card.get("conclusion") or "未映射自选",
            }
            for card in unmapped
        ],
        "watchlist": [{"symbol": row.get("symbol"), "name": row.get("name")} for row in watch_rows],
        "gaps": {
            "watchlist": not watch_rows,
            "events": not events,
            "quotes": False,
        },
        "diagnostics": {
            "data_mode": (coverage or {}).get("data_mode"),
            "live": (coverage or {}).get("live"),
            "event_count": len(events or []),
        },
    }
