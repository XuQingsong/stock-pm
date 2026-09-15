"""Direction × intensity scale for event→ticker impact.

Frozen chips: 深绿 / 浅绿 / 灰 / 黄 / 浅红 / 深红.
Do not paint deep colors without inspectable exposure + evidence.
"""

from __future__ import annotations

from typing import Any

from .copy import direction_side

IMPACT_SCALE = (
    "deep-green",
    "light-green",
    "gray",
    "yellow",
    "light-red",
    "deep-red",
)

LABELS = {
    "deep-green": "深绿 · 强烈利多",
    "light-green": "浅绿",
    "gray": "灰",
    "yellow": "黄 · 分歧",
    "light-red": "浅红 · 偏空",
    "deep-red": "深红 · 强烈利空",
}

BARS = {
    "deep-green": 3,
    "light-green": 2,
    "gray": 1,
    "yellow": 2,
    "light-red": 2,
    "deep-red": 3,
}

RANK = {
    "deep-red": 0,
    "deep-green": 0,
    "light-red": 1,
    "light-green": 1,
    "yellow": 2,
    "gray": 3,
}

DIRECT_CHANNELS = frozenset({"company", "commodity_revenue"})
INDIRECT_CHANNELS = frozenset({"supply_chain", "duration", "demand", "credit_conditions", "risk_premium"})

DIRECT_MECHANISMS = frozenset(
    {
        "company_filing",
        "company_earnings",
        "commodity_price_to_producer_revenue",
    }
)


def impact_label(kind: str, *, side: str | None = None) -> str:
    if kind == "gray" and side == "bull":
        return "灰偏多"
    if kind == "gray" and side == "bear":
        return "灰偏空"
    if kind == "gray" and side == "none":
        return "灰·不受影响"
    return LABELS.get(kind, LABELS["gray"])


def bars_for(kind: str) -> int:
    return int(BARS.get(kind, 1))


def rank_for(kind: str) -> int:
    return int(RANK.get(kind, 3))


def _directness(hit: dict[str, Any] | None) -> str:
    row = hit or {}
    channel = str(row.get("channel") or "")
    mechanism = str(row.get("mechanism") or "")
    if channel in DIRECT_CHANNELS or mechanism in DIRECT_MECHANISMS:
        return "direct"
    if channel in INDIRECT_CHANNELS:
        return "indirect"
    return "weak"


def grade_impact(
    *,
    side: str | None,
    hit: dict[str, Any] | None = None,
    closed_loop: bool = False,
    confidence: str | None = None,
    withheld: bool = False,
    conflict: bool = False,
) -> dict[str, Any]:
    """Paint a chip. Missing evidence stays gray/yellow, never a fake deep color."""
    direction = direction_side(side)
    directness = _directness(hit)
    conf = str(confidence or "").lower()
    if conflict or direction == "watch":
        kind = "yellow"
    elif withheld or not hit:
        kind = "gray"
        direction = "none" if not hit else direction
    elif not closed_loop and conf in {"insufficient", "limited", "revoked", ""}:
        kind = "yellow" if direction == "watch" else "gray"
    elif direction == "bull":
        if directness == "direct" and closed_loop and conf in {"high", "medium", ""}:
            kind = "deep-green"
        elif directness in {"direct", "indirect"}:
            kind = "light-green"
        else:
            kind = "gray"
    elif direction == "bear":
        if directness == "direct" and closed_loop and conf in {"high", "medium", ""}:
            kind = "deep-red"
        elif directness in {"direct", "indirect"}:
            kind = "light-red"
        else:
            kind = "gray"
    else:
        kind = "gray"
    return {
        "kind": kind,
        "label": impact_label(kind, side=direction),
        "bars": bars_for(kind),
        "side": direction,
        "directness": directness,
        "rank": rank_for(kind),
    }
