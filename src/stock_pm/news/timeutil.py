"""Publish-time normalization and US equity session mapping.

Every vendor timestamp becomes a UTC instant plus two honesty markers:
``precision`` (second / minute / day) and ``tz_basis`` (explicit offset,
assumed zone, or date only). Relative strings ("3 hours ago") are refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from stock_pm.calendar import NY_TZ, is_early_close, is_trading_day, next_trading_day

UTC = timezone.utc

PREMARKET_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
AFTER_HOURS_CLOSE = time(20, 0)
EARLY_AFTER_HOURS_CLOSE = time(17, 0)

SESSIONS = ("premarket", "regular", "after_hours", "overnight", "closed", "unknown")

_RELATIVE = re.compile(r"\b(ago|yesterday|today|tomorrow|last\s+(?:week|month))\b", re.I)
_COMPACT = re.compile(r"^(\d{8})T(\d{4})(\d{2})?$")
_HMS = re.compile(r"\d{2}:\d{2}:\d{2}")
_DATE_ONLY_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y")


@dataclass(frozen=True, slots=True)
class PublishedTime:
    utc: datetime | None
    precision: str | None
    tz_basis: str
    local_date: date | None
    raw: str | None

    @property
    def iso(self) -> str | None:
        return self.utc.isoformat() if self.utc else None

    @property
    def has_time_of_day(self) -> bool:
        return self.precision in {"second", "minute"}

    @property
    def tz_explicit(self) -> bool:
        return self.tz_basis == "explicit"


def _unparsed(raw: str | None) -> PublishedTime:
    return PublishedTime(utc=None, precision=None, tz_basis="unparsed", local_date=None, raw=raw)


def _from_aware(stamp: datetime, *, precision: str, tz_basis: str, raw: str) -> PublishedTime:
    instant = stamp.astimezone(UTC).replace(microsecond=0)
    return PublishedTime(
        utc=instant,
        precision=precision,
        tz_basis=tz_basis,
        local_date=instant.astimezone(NY_TZ).date(),
        raw=raw,
    )


def _date_only(day: date, raw: str) -> PublishedTime:
    # Anchored at 00:00 ET so the ET calendar date survives; never shown as a time.
    anchor = datetime.combine(day, time(0, 0), tzinfo=NY_TZ).astimezone(UTC)
    return PublishedTime(utc=anchor, precision="day", tz_basis="date_only", local_date=day, raw=raw)


def normalize_published(value: object, *, naive_tz: str = "America/New_York") -> PublishedTime:
    """Parse a vendor publish time.

    ``naive_tz`` is the zone assumed when the vendor omits an offset; the
    result then carries ``tz_basis="assumed:<zone>"`` so callers can flag it.
    """
    if value is None:
        return _unparsed(None)
    if isinstance(value, datetime):
        raw = value.isoformat()
        if value.tzinfo is None:
            return _from_aware(value.replace(tzinfo=ZoneInfo(naive_tz)), precision="second", tz_basis=f"assumed:{naive_tz}", raw=raw)
        return _from_aware(value, precision="second", tz_basis="explicit", raw=raw)
    if isinstance(value, date):
        return _date_only(value, value.isoformat())
    text = str(value).strip()
    if not text or _RELATIVE.search(text):
        return _unparsed(text or None)

    compact = _COMPACT.match(text)
    if compact:
        day, hhmm, seconds = compact.groups()
        try:
            stamp = datetime.strptime(day + hhmm + (seconds or "00"), "%Y%m%d%H%M%S")
        except ValueError:
            return _unparsed(text)
        return _from_aware(
            stamp.replace(tzinfo=ZoneInfo(naive_tz)),
            precision="second" if seconds else "minute",
            tz_basis=f"assumed:{naive_tz}",
            raw=text,
        )

    for fmt in _DATE_ONLY_FORMATS:
        try:
            return _date_only(datetime.strptime(text, fmt).date(), text)
        except ValueError:
            continue

    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        stamp = None
    if stamp is not None:
        precision = "second" if _HMS.search(text) else "minute"
        if stamp.tzinfo is None:
            return _from_aware(stamp.replace(tzinfo=ZoneInfo(naive_tz)), precision=precision, tz_basis=f"assumed:{naive_tz}", raw=text)
        return _from_aware(stamp, precision=precision, tz_basis="explicit", raw=text)

    try:
        stamp = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return _unparsed(text)
    # RFC 2822 "-0000" means "zone unknown"; parsedate returns a naive value for it.
    if stamp.tzinfo is None:
        return _from_aware(stamp.replace(tzinfo=ZoneInfo(naive_tz)), precision="second", tz_basis=f"assumed:{naive_tz}", raw=text)
    return _from_aware(stamp, precision="second", tz_basis="explicit", raw=text)


def _regular_close(day: date) -> time:
    return EARLY_CLOSE if is_early_close(day) else REGULAR_CLOSE


def _extended_close(day: date) -> time:
    return EARLY_AFTER_HOURS_CLOSE if is_early_close(day) else AFTER_HOURS_CLOSE


def market_session(instant: datetime | None) -> str:
    """Classify an instant into the US equity session it falls in (ET)."""
    if instant is None:
        return "unknown"
    local = instant.astimezone(NY_TZ)
    day = local.date()
    clock = local.time()
    if not is_trading_day(day):
        return "closed"
    if clock < PREMARKET_OPEN:
        return "overnight"
    if clock < REGULAR_OPEN:
        return "premarket"
    if clock < _regular_close(day):
        return "regular"
    if clock < _extended_close(day):
        return "after_hours"
    return "overnight"


def reaction_date(instant: datetime | None) -> date | None:
    """First regular session that can price information published at ``instant``."""
    if instant is None:
        return None
    local = instant.astimezone(NY_TZ)
    day = local.date()
    if is_trading_day(day) and local.time() < _regular_close(day):
        return day
    return next_trading_day(day)


def session_fields(published: PublishedTime) -> dict[str, object]:
    """Session and reaction date, or honest unknowns for date-only stamps."""
    if not published.has_time_of_day or published.utc is None:
        return {"session": "unknown", "reaction_date": None}
    return {"session": market_session(published.utc), "reaction_date": reaction_date(published.utc)}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def minutes_between(earlier: datetime | None, later: datetime | None) -> float | None:
    if earlier is None or later is None:
        return None
    return round((later - earlier) / timedelta(minutes=1), 1)
