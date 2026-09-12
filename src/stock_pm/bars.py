"""Daily bar normalization: trading session, adjustment tag, OHLC constraints."""

from __future__ import annotations

from datetime import date, datetime, time as clock_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .decision.facts import ohlc_constraint_errors
from .decision.numbers import as_number


NY = ZoneInfo("America/New_York")
DAILY_ADJUSTMENT = "split"
DAILY_ADJUSTMENT_NOTE = "split-adjusted; not dividend-adjusted; never mix with unadjusted closes"


def is_us_trading_day(value: date) -> bool:
    return value.weekday() < 5


def last_completed_session_end(now: datetime | None = None) -> datetime:
    eastern = (now or datetime.now(timezone.utc)).astimezone(NY)
    session_close = datetime.combine(eastern.date(), clock_time(16, 0), tzinfo=NY)
    cursor = eastern
    if cursor < session_close:
        cursor = cursor - timedelta(days=1)
    while not is_us_trading_day(cursor.date()):
        cursor = cursor - timedelta(days=1)
    return datetime.combine(cursor.date(), clock_time(16, 0), tzinfo=NY).astimezone(timezone.utc)


def bar_session_date(bar_time: Any) -> date | None:
    if bar_time is None:
        return None
    if isinstance(bar_time, datetime):
        return bar_time.astimezone(NY).date()
    text = str(bar_time).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(NY).date()
    except ValueError:
        return None


def ohlc_tuple(row: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    return (
        as_number(row.get("open_price") if "open_price" in row else row.get("open") or row.get("o")),
        as_number(row.get("high_price") if "high_price" in row else row.get("high") or row.get("h")),
        as_number(row.get("low_price") if "low_price" in row else row.get("low") or row.get("l")),
        as_number(row.get("close_price") if "close_price" in row else row.get("close") or row.get("c")),
    )


def is_valid_ohlc(row: dict[str, Any]) -> bool:
    open_px, high, low, close = ohlc_tuple(row)
    return not ohlc_constraint_errors(open_px, high, low, close)


def decorate_bar(
    row: dict[str, Any],
    *,
    fetched_at: str,
    adjustment: str = DAILY_ADJUSTMENT,
    source: str,
) -> dict[str, Any]:
    open_px, high, low, close = ohlc_tuple(row)
    errors = ohlc_constraint_errors(open_px, high, low, close)
    session = bar_session_date(row.get("bar_time") or row.get("t"))
    payload = dict(row)
    payload.update(
        {
            "open_price": open_px,
            "high_price": high,
            "low_price": low,
            "close_price": close,
            "adjustment": adjustment,
            "adjustment_note": DAILY_ADJUSTMENT_NOTE,
            "session": "America/New_York",
            "session_date": session.isoformat() if session else None,
            "trading_day": bool(session and is_us_trading_day(session)),
            "observed_at": payload.get("bar_time") or payload.get("t"),
            "as_of": session.isoformat() if session else None,
            "fetched_at": fetched_at,
            "frequency": "daily",
            "status": "invalid" if errors else "ok",
            "ohlc_errors": errors,
            "source": source,
        }
    )
    return payload


def usable_daily_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_valid_ohlc(row)]


def partition_ohlc_rows(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, Any]]]:
    """Split rows into valid/invalid. Never deletes."""
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for row in rows:
        mapping = dict(row) if not isinstance(row, dict) else row
        if is_valid_ohlc(mapping):
            valid.append(mapping)
        else:
            invalid.append(mapping)
    return {"valid": valid, "invalid": invalid}
