"""UTC-normalized timestamps for kernel comparisons."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def as_of_status(value: str | None) -> str:
    """Return 'ok', 'missing_as_of', or 'invalid_as_of'."""
    dt = parse_as_of(value)
    if dt is None:
        return "missing_as_of"
    if dt == "invalid":
        return "invalid_as_of"
    return "ok"


def parse_as_of(value: str | None) -> datetime | None | str:
    """Return timezone-aware UTC datetime, None if missing, or 'invalid'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return "invalid"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def as_of_span(values: list[str | None]) -> timedelta | None:
    parsed: list[datetime] = []
    for value in values:
        dt = parse_as_of(value)
        if dt is None or dt == "invalid":
            return None
        parsed.append(dt)
    if not parsed:
        return None
    return max(parsed) - min(parsed)
