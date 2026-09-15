"""Earnings-window price reactions from daily closes. No ticker-specific logic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .extract import to_number


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def index_closes(rows: list[dict[str, Any]] | None) -> list[tuple[date, float]]:
    by_day: dict[date, float] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        session = _as_date(row.get("session_date") or row.get("bar_time") or row.get("date"))
        price = to_number(row.get("close_price") or row.get("close") or row.get("value"))
        if session is None or price is None:
            continue
        by_day[session] = price
    return sorted(by_day.items(), key=lambda item: item[0])


def _find_on_or_after(sessions: list[tuple[date, float]], target: date) -> int | None:
    for idx, (session, _price) in enumerate(sessions):
        if session >= target:
            return idx
    return None


def _ret(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round(100.0 * (new / old - 1.0), 2)


def _px(sessions: list[tuple[date, float]], idx: int | None) -> float | None:
    if idx is None or idx < 0 or idx >= len(sessions):
        return None
    return sessions[idx][1]


def reaction_date_for(report_date: Any, report_timing: str | None) -> date | None:
    day = _as_date(report_date)
    if day is None:
        return None
    timing = str(report_timing or "").lower()
    if timing in {"before_market", "during_market"}:
        return day
    return day + timedelta(days=1)


def window_returns(sessions: list[tuple[date, float]], report_date: Any, report_timing: str | None) -> dict[str, float | None]:
    target = reaction_date_for(report_date, report_timing)
    empty = {
        "pre_5d_return_pct": None,
        "day_return_pct": None,
        "post_1d_return_pct": None,
        "post_3d_return_pct": None,
        "post_5d_return_pct": None,
    }
    if target is None or not sessions:
        return empty
    idx = _find_on_or_after(sessions, target)
    if idx is None:
        return empty
    before = _px(sessions, idx - 1)
    day = _px(sessions, idx)
    pre5_start = _px(sessions, idx - 6)
    return {
        "pre_5d_return_pct": _ret(before, pre5_start),
        "day_return_pct": _ret(day, before),
        "post_1d_return_pct": _ret(_px(sessions, idx), before),
        "post_3d_return_pct": _ret(_px(sessions, idx + 2), before),
        "post_5d_return_pct": _ret(_px(sessions, idx + 4), before),
    }


def relative_return(stock: float | None, bench: float | None) -> float | None:
    if stock is None or bench is None:
        return None
    return round(stock - bench, 2)


def price_reaction_for_print(
    report_date: Any,
    report_timing: str | None,
    stock: list[tuple[date, float]],
    spy: list[tuple[date, float]] | None = None,
    qqq: list[tuple[date, float]] | None = None,
) -> dict[str, float | None]:
    own = window_returns(stock, report_date, report_timing)
    spy_win = window_returns(spy or [], report_date, report_timing) if spy else {}
    qqq_win = window_returns(qqq or [], report_date, report_timing) if qqq else {}
    own["vs_spy_1d_pct"] = relative_return(own.get("post_1d_return_pct"), spy_win.get("post_1d_return_pct"))
    own["vs_spy_5d_pct"] = relative_return(own.get("post_5d_return_pct"), spy_win.get("post_5d_return_pct"))
    own["vs_qqq_1d_pct"] = relative_return(own.get("post_1d_return_pct"), qqq_win.get("post_1d_return_pct"))
    own["vs_qqq_5d_pct"] = relative_return(own.get("post_5d_return_pct"), qqq_win.get("post_5d_return_pct"))
    return own
