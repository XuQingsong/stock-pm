"""Decision dataset clock. Do not confuse wall-clock today with missing facts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .timeparse import parse_as_of

MACRO_LOOKBACK_DAYS = 180


def as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    if isinstance(value, date):
        return value
    parsed = parse_as_of(str(value))
    if parsed is None or parsed == "invalid":
        return None
    return parsed.date()


def dataset_as_of(
    *,
    bars: Iterable[dict[str, Any]] = (),
    earnings: Iterable[dict[str, Any]] = (),
    macros: Iterable[dict[str, Any]] = (),
    today: date | None = None,
) -> date:
    """Latest as_of present in the bundle. Wall-clock today is last-resort only."""
    found: list[date] = []
    for row in bars:
        stamp = as_date(row.get("bar_time") or row.get("as_of"))
        if stamp:
            found.append(stamp)
    for row in earnings:
        stamp = as_date(row.get("report_date") or row.get("as_of"))
        if stamp:
            found.append(stamp)
    for row in macros:
        stamp = as_date(row.get("event_time") or row.get("as_of"))
        if stamp:
            found.append(stamp)
    if found:
        return max(found)
    return today or date.today()


def macro_window(as_of: date, *, days: int = MACRO_LOOKBACK_DAYS) -> tuple[date, date]:
    return as_of - timedelta(days=days), as_of


def partition_macros(
    events: Iterable[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split macros into in-window, older than start (stale), and after end (mismatch)."""
    inside: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    mismatch: list[dict[str, Any]] = []
    for event in events:
        stamp = as_date(event.get("event_time") or event.get("as_of"))
        if stamp is None:
            continue
        if start <= stamp <= end:
            inside.append(event)
        elif stamp < start:
            stale.append(event)
        else:
            mismatch.append(event)
    return inside, stale, mismatch
