from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

_HOLIDAY_NAMES = {
    "new_year": "元旦",
    "mlk": "马丁路德金日",
    "presidents": "总统日",
    "good_friday": "耶稣受难日",
    "memorial": "阵亡将士纪念日",
    "juneteenth": "六月节",
    "independence": "独立日",
    "labor": "劳动节",
    "thanksgiving": "感恩节",
    "christmas": "圣诞节",
}


def ny_today(now: datetime | None = None) -> date:
    current = now or datetime.now(tz=NY_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NY_TZ)
    return current.astimezone(NY_TZ).date()


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year, 12, 31)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nyse_holidays(year: int) -> dict[date, str]:
    mapping = {
        _observed(date(year, 1, 1)): "new_year",
        _nth_weekday(year, 1, 0, 3): "mlk",
        _nth_weekday(year, 2, 0, 3): "presidents",
        _easter(year) - timedelta(days=2): "good_friday",
        _last_weekday(year, 5, 0): "memorial",
        _observed(date(year, 6, 19)): "juneteenth",
        _observed(date(year, 7, 4)): "independence",
        _nth_weekday(year, 9, 0, 1): "labor",
        _nth_weekday(year, 11, 3, 4): "thanksgiving",
        _observed(date(year, 12, 25)): "christmas",
    }
    return mapping


def holiday_name(day: date) -> str | None:
    key = nyse_holidays(day.year).get(day)
    return _HOLIDAY_NAMES.get(key) if key else None


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and holiday_name(day) is None


def last_trading_day(as_of: date) -> date:
    cursor = as_of
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def session_status(day: date) -> dict[str, object]:
    if day.weekday() >= 5:
        return {
            "is_trading_day": False,
            "reason": "weekend",
            "holiday_name": None,
            "label": "周末休市",
        }
    name = holiday_name(day)
    if name:
        return {
            "is_trading_day": False,
            "reason": "holiday",
            "holiday_name": name,
            "label": f"{name}，美股休市",
        }
    return {
        "is_trading_day": True,
        "reason": "trading",
        "holiday_name": None,
        "label": None,
    }
