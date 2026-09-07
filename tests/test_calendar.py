from datetime import date

from stock_pm.calendar import (
    holiday_name,
    is_trading_day,
    last_trading_day,
    session_status,
)
from stock_pm.queries import QueryMixin


def test_labor_day_2026_is_closed() -> None:
    day = date(2026, 9, 7)
    assert holiday_name(day) == "劳动节"
    assert is_trading_day(day) is False
    assert last_trading_day(day) == date(2026, 9, 4)
    assert session_status(day)["reason"] == "holiday"
    assert session_status(day)["label"] == "劳动节，美股休市"


def test_weekend_and_independence_observed() -> None:
    assert is_trading_day(date(2026, 9, 5)) is False
    assert session_status(date(2026, 9, 5))["reason"] == "weekend"
    assert last_trading_day(date(2026, 9, 5)) == date(2026, 9, 4)
    assert holiday_name(date(2026, 7, 3)) == "独立日"
    assert is_trading_day(date(2026, 9, 4)) is True
    assert is_trading_day(date(2026, 9, 8)) is True


class _SessionStub(QueryMixin):
    def reviews_by_date(self, trade_date):
        return [{"symbol": "AAPL"}] if trade_date == "2026-09-04" else []

    def latest_review_date(self):
        return "2026-09-04"

    def latest_bar_date(self):
        return "2026-09-04"


def test_market_session_defaults_to_last_review() -> None:
    session = _SessionStub().market_session("2026-09-07")
    assert session["is_trading_day"] is False
    assert session["has_reviews"] is False
    assert session["last_trading_date"] == "2026-09-04"
    assert session["default_review_date"] == "2026-09-04"
    open_day = _SessionStub().market_session("2026-09-04")
    assert open_day["is_trading_day"] is True
    assert open_day["has_reviews"] is True
    assert open_day["status"] == "reviewed"
