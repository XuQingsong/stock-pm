"""UTC-normalized timestamps for kernel comparisons."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


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
