"""Inspectable event → ticker mapping.

Not keyword paste: a mapping is kept only when a channel + mechanism +
why_relevant sentence exist. Watchlist themes come from the live row, not
from scanning the headline for every ticker.
"""

from __future__ import annotations

from typing import Any

from stock_pm.events.exposure import attach_exposures
from stock_pm.events.types import TrustedEvent

from .copy import direction_side, scope_label
from .strength import grade_impact


def _watch_index(watch: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in watch or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            out[symbol] = row
    return out


def _event_dict(event: TrustedEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, TrustedEvent):
        return event.as_dict()
    return dict(event or {})


def _analysis(event: TrustedEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, TrustedEvent):
        return dict(event.analysis or {})
    payload = event or {}
    analysis = payload.get("analysis")
    return dict(analysis) if isinstance(analysis, dict) else {}


def _as_trusted(event: TrustedEvent | dict[str, Any]) -> TrustedEvent | None:
    if isinstance(event, TrustedEvent):
        return event
    return None


def event_side(analysis: dict[str, Any]) -> str:
    withheld = analysis.get("withheld") or {}
    raw = withheld.get("direction")
    if not raw:
        bound = analysis.get("direction")
        if isinstance(bound, dict):
            raw = bound.get("text")
        else:
            raw = bound
    if analysis.get("can_form_direction") is False:
        return "none"
    return direction_side(raw)


def map_event(
    event: TrustedEvent | dict[str, Any],
    watch: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return inspectable per-ticker rows. Empty means unmapped, not 'all names'."""
    wanted = [str(row.get("symbol") or "").upper() for row in (watch or []) if row.get("symbol")]
    trusted = _as_trusted(event)
    rows: list[dict[str, Any]] = []
    if trusted is not None:
        attached = attach_exposures(trusted, wanted, watch_rows=watch)
        for hit in attached:
            if not _inspectable(hit):
                continue
            rows.append(hit)
        return rows
    # Dict-only fallback: keep already-attached exposures if they are inspectable.
    analysis = _analysis(event)
    payload = _event_dict(event)
    for item in list(analysis.get("exposures") or payload.get("exposures") or []):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if wanted and symbol not in wanted:
            continue
        if not _inspectable(item):
            continue
        rows.append({**item, "symbol": symbol})
    return rows


def _inspectable(hit: dict[str, Any] | None) -> bool:
    row = hit or {}
    return bool(
        str(row.get("symbol") or "").strip()
        and str(row.get("channel") or "").strip()
        and str(row.get("mechanism") or "").strip()
        and str(row.get("why_relevant") or row.get("why") or "").strip()
    )


def map_news_to_watchlist(item: dict[str, Any], watch: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Company news stays on the ingested symbol. Theme overlap is industry-weak.

    Never greps other tickers out of the headline.
    """
    index = _watch_index(watch)
    symbol = str(item.get("symbol") or "").upper()
    rows: list[dict[str, Any]] = []
    if symbol in index:
        rows.append(
            {
                "symbol": symbol,
                "channel": "company",
                "mechanism": "watchlist_ingested_article",
                "why_relevant": "该条新闻按自选标的入库，不是从标题里扫全部代码",
                "scope": "company",
                "strength_hint": "indirect",
            }
        )
    themes = [str(theme) for theme in (item.get("themes") or []) if theme]
    if not themes:
        return rows
    seen = {symbol} if symbol else set()
    for row in watch or []:
        other = str(row.get("symbol") or "").upper()
        if not other or other in seen:
            continue
        live_themes = {str(theme) for theme in (row.get("themes") or []) if theme}
        overlap = sorted(set(themes) & live_themes)
        if not overlap:
            continue
        seen.add(other)
        joined = "、".join(overlap)
        rows.append(
            {
                "symbol": other,
                "channel": "theme_overlap",
                "mechanism": "watchlist_theme_intersection",
                "why_relevant": f"新闻主题 {joined} 与自选主题相交，不是标题点名该代码",
                "scope": "industry",
                "strength_hint": "weak",
            }
        )
    return rows


def ticker_impacts(
    event: TrustedEvent | dict[str, Any],
    watch: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    analysis = _analysis(event)
    side = event_side(analysis)
    withheld = (analysis.get("withheld") or {}).get("status") != "observable"
    closed = bool(analysis.get("closed_loop"))
    confidence = None
    bound = analysis.get("confidence")
    if isinstance(bound, dict):
        confidence = bound.get("text")
    elif bound:
        confidence = str(bound)
    conflict = int(analysis.get("conflict_count") or 0) > 0
    out = []
    for hit in map_event(event, watch):
        grade = grade_impact(
            side=side,
            hit=hit,
            closed_loop=closed,
            confidence=confidence,
            withheld=withheld,
            conflict=conflict,
        )
        out.append(
            {
                "symbol": hit["symbol"],
                "channel": hit.get("channel"),
                "mechanism": hit.get("mechanism"),
                "why": hit.get("why_relevant") or hit.get("why"),
                "inspectable": True,
                **grade,
            }
        )
    return out


def event_scope(event: TrustedEvent | dict[str, Any], mapped: list[dict[str, Any]]) -> str:
    payload = _event_dict(event)
    event_type = str(payload.get("event_type") or "")
    if event_type in {"company_filing", "company_earnings"}:
        return scope_label("company", event_type)
    if any(row.get("directness") == "direct" for row in mapped):
        if event_type in {"company_filing", "company_earnings"}:
            return "公司级"
        return "行业级"
    if mapped:
        return scope_label(payload.get("scope"), event_type)
    return scope_label(payload.get("scope"), event_type)
