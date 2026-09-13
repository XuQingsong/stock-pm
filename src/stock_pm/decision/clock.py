"""Decision dataset clock: observation time only, never future event dates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .timeparse import parse_as_of

MACRO_LOOKBACK_DAYS = 180

# When the print/bar was observed. These may drive the dataset clock.
OBSERVATION_FIELDS = ("observed_at", "ingested_at", "synced_at", "source_as_of")
BAR_OBSERVATION_FIELDS = OBSERVATION_FIELDS + ("bar_time", "as_of")
# Earnings release/fiscal dates are event timing, not observation.
EARNINGS_OBSERVATION_FIELDS = OBSERVATION_FIELDS
# Macro event_time is the scheduled/effective date and must not drive the clock.
MACRO_OBSERVATION_FIELDS = OBSERVATION_FIELDS
EVENT_TIME_FIELDS = ("event_time", "release_date", "report_date", "period_end", "fiscal_period")


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


def _first_date(row: dict[str, Any], fields: tuple[str, ...]) -> date | None:
    for key in fields:
        if key not in row or row.get(key) is None:
            continue
        stamp = as_date(row.get(key))
        if stamp:
            return stamp
    return None


def observation_date(row: dict[str, Any], *, kind: str) -> date | None:
    if kind == "bar":
        return _first_date(row, BAR_OBSERVATION_FIELDS)
    if kind == "earnings":
        return _first_date(row, EARNINGS_OBSERVATION_FIELDS)
    return _first_date(row, MACRO_OBSERVATION_FIELDS)


def event_date(row: dict[str, Any]) -> date | None:
    return _first_date(row, ("event_time", "release_date", "report_date", "period_end"))


def is_observed_macro(event: dict[str, Any]) -> bool:
    return event.get("actual") is not None


def dataset_as_of(
    *,
    bars: Iterable[dict[str, Any]] = (),
    earnings: Iterable[dict[str, Any]] = (),
    macros: Iterable[dict[str, Any]] = (),
) -> date | None:
    """Latest observation timestamp. Never uses event_time/release_date/fiscal_period or date.today()."""
    found: list[date] = []
    for row in bars:
        stamp = observation_date(row, kind="bar")
        if stamp:
            found.append(stamp)
    for row in earnings:
        stamp = observation_date(row, kind="earnings")
        if stamp:
            found.append(stamp)
    for row in macros:
        stamp = observation_date(row, kind="macro")
        if stamp:
            found.append(stamp)
    return max(found) if found else None


def macro_window(as_of: date, *, days: int = MACRO_LOOKBACK_DAYS) -> tuple[date, date]:
    return as_of - timedelta(days=days), as_of


@dataclass
class MacroPartition:
    inside: list[dict[str, Any]] = field(default_factory=list)
    stale: list[dict[str, Any]] = field(default_factory=list)
    mismatch: list[dict[str, Any]] = field(default_factory=list)
    scheduled: list[dict[str, Any]] = field(default_factory=list)


def classify_macros(
    events: Iterable[dict[str, Any]],
    clock: date | None,
    *,
    days: int = MACRO_LOOKBACK_DAYS,
) -> MacroPartition:
    """Split macros by observation vs schedule. Future event_time never ages current facts."""
    out = MacroPartition()
    start, end = macro_window(clock, days=days) if clock is not None else (None, None)
    for event in events:
        occurred = is_observed_macro(event)
        when = event_date(event)
        if not occurred:
            out.scheduled.append(event)
            continue
        if clock is None or start is None or end is None:
            # Have a print but no observation clock: cannot place it on the timeline.
            out.scheduled.append(event)
            continue
        if when is None or when > clock:
            out.scheduled.append(event)
            continue
        if start <= when <= end:
            out.inside.append(event)
        elif when < start:
            out.stale.append(event)
        else:
            out.mismatch.append(event)
    return out


def partition_macros(
    events: Iterable[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Backward-compatible split; scheduled/future prints are not treated as in-window facts."""
    clock = end
    parts = classify_macros(events, clock)
    return parts.inside, parts.stale, parts.mismatch
