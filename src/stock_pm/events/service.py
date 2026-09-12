"""Build coverage + selective event views for market and stock pages."""

from __future__ import annotations

from typing import Any

from stock_pm.config import Settings

from .analyze import DISPLAY_SYMBOLS, analyze_event, symbol_event_view
from .dedupe import build_events
from .providers import GoogleDiscoveryProvider, OfficialFeedProvider, provider_coverage
from .types import TrustedEvent


_CACHE: dict[str, Any] = {"events": None, "coverage": None}


def build_event_book(settings: Settings | None = None, *, refresh: bool = False) -> list[TrustedEvent]:
    if _CACHE["events"] is not None and not refresh:
        return list(_CACHE["events"])
    official = OfficialFeedProvider(settings).discover()
    google = GoogleDiscoveryProvider(settings)
    discovered = official
    if google.configured():
        discovered = official + google.discover()
    events = build_events(discovered)
    for event in events:
        analyze_event(event)
    _CACHE["events"] = events
    _CACHE["coverage"] = None
    return list(events)


def coverage(settings: Settings | None = None, events: list[TrustedEvent] | None = None) -> dict[str, Any]:
    rows = events if events is not None else build_event_book(settings)
    providers = provider_coverage(settings)
    official_ok = providers["official_feed"]["status"] == "ok"
    google = providers["google_cse"]
    conflicts = sum(int((event.analysis or {}).get("conflict_count") or 0) for event in rows)
    return {
        "status": "ok" if official_ok else "degraded",
        "coverage": "partial" if google["status"] != "ok" else "complete_discovery",
        "last_success": max((event.updated_at for event in rows), default=None),
        "source_count": sum(len(event.sources) for event in rows),
        "event_count": len(rows),
        "conflict_count": conflicts,
        "reason_code": google.get("reason_code") if google["status"] != "ok" else None,
        "providers": providers,
        "affects_chain": "events",
        "does_not_affect": ["price", "earnings", "macro_rates"],
    }


def market_center(settings: Settings | None = None) -> dict[str, Any]:
    events = build_event_book(settings)
    return {
        "title": "市场事件中心",
        "coverage": coverage(settings, events),
        "events": [event.as_dict() for event in events],
    }


def stock_events(symbol: str, settings: Settings | None = None) -> dict[str, Any]:
    events = build_event_book(settings)
    selected = []
    risk_state = None
    for event in events:
        if event.event_type == "vix_risk" and risk_state is None:
            analysis = event.analysis or {}
            risk_state = {
                "role": "risk_confirmation_only",
                "does_not_imply": "个股涨跌方向",
                "event_id": event.event_id,
                "canonical_title": event.canonical_title,
                "confidence": (analysis.get("confidence") or {}).get("text"),
                "evidence_refs": analysis.get("evidence_refs") or [],
            }
        view = symbol_event_view(event, symbol)
        if view:
            selected.append(view)
    return {
        "symbol": symbol.upper(),
        "coverage": coverage(settings, events),
        "events": selected,
        "risk_state": risk_state,
        "note": "个股页只显示经行业映射和公司暴露判定相关的事件，并说明为什么相关。VIX 只确认风险，不复制成个股涨跌。",
    }


def event_detail(event_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    for event in build_event_book(settings):
        if event.event_id == event_id:
            return event.as_dict()
    return None


def reset_cache() -> None:
    _CACHE["events"] = None
    _CACHE["coverage"] = None


def display_symbols() -> tuple[str, ...]:
    return DISPLAY_SYMBOLS
