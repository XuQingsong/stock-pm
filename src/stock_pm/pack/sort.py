"""Event ranking for featured vs carousel vs unmapped fold."""

from __future__ import annotations

from typing import Any


def event_sort_key(card: dict[str, Any]) -> tuple:
    mapped = bool(card.get("mapped"))
    kind_rank = int(card.get("rank") if card.get("rank") is not None else 9)
    closed = 0 if card.get("closed_loop") else 1
    scope = str(card.get("scope_label") or "")
    scope_rank = {"公司级": 0, "行业级": 1, "市场级": 2, "宏观": 3}.get(scope, 4)
    published = str(card.get("published_at") or card.get("event_time") or "")
    title = str(card.get("title") or "")
    return (0 if mapped else 1, kind_rank, closed, scope_rank, published and 0 or 1, published, title)


def split_events(cards: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(cards, key=event_sort_key)
    featured = None
    rest: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for card in ordered:
        if not card.get("mapped"):
            unmapped.append(card)
            continue
        can_feature = card.get("featured_ok", True)
        if featured is None and can_feature:
            featured = {**card, "featured": True}
        else:
            rest.append({**card, "featured": False, "compact": True})
    return {"featured": featured, "carousel": rest, "unmapped": unmapped}
