from stock_pm.bars import isolated_bar_record, plan_daily_bar_writes
from stock_pm.persist import PersistMixin


class _SpyPersist(PersistMixin):
    def __init__(self) -> None:
        self.pool_touched = False
        self.pool = self
        self.sql = []

    def connection(self):
        self.pool_touched = True
        raise AssertionError("quarantine without confirm must not touch the database")


def test_quarantine_without_confirm_does_not_delete():
    store = _SpyPersist()
    assert store.quarantine_invalid_daily_bars() == 0
    assert store.quarantine_invalid_daily_bars(confirm=False) == 0
    assert store.isolate_invalid_daily_bars() == {"isolated": 0, "deleted": 0, "valid_untouched": 0}
    assert store.pool_touched is False


def test_alpaca_startup_does_not_call_quarantine_or_delete():
    from pathlib import Path

    text = Path("src/stock_pm/alpaca.py").read_text()
    assert "quarantine_invalid_daily_bars" not in text
    assert "isolate_invalid_daily_bars" not in text
    assert "DELETE FROM price_bars" not in text


def test_persist_has_no_silent_price_bar_delete():
    from pathlib import Path

    text = Path("src/stock_pm/persist.py").read_text()
    assert "DELETE FROM price_bars" not in text
    assert "price_bar_quarantine" in text


def test_isolated_bar_record_is_recoverable_and_not_deleted():
    row = isolated_bar_record(
        {"symbol": "NVDA", "bar_time": "2026-09-10T20:00:00+00:00", "close_price": 122},
        isolated_at="2026-09-11T01:00:00+00:00",
    )
    assert row["recoverable"] is True
    assert row["deleted"] is False
    assert row["reason"] == "invalid_ohlc"


def test_plan_daily_writes_never_deletes_valid_history():
    existing_valid = {
        "symbol": "NVDA",
        "bar_size": "1d",
        "bar_time": "2025-01-15T21:00:00+00:00",
        "open_price": 130.0,
        "high_price": 132.0,
        "low_price": 129.0,
        "close_price": 131.0,
    }
    incoming_invalid = {
        "symbol": "NVDA",
        "bar_size": "1d",
        "bar_time": "2026-09-10T20:00:00+00:00",
        "open_price": 116.8,
        "high_price": 118.5,
        "low_price": 115.0,
        "close_price": 122.0,
    }
    plan = plan_daily_bar_writes([existing_valid], [incoming_invalid, existing_valid])
    assert plan["delete"] == []
    assert plan["keep_existing_valid"][0]["bar_time"] == existing_valid["bar_time"]
    assert [row["bar_time"] for row in plan["isolate"]] == [incoming_invalid["bar_time"]]
    assert any(row["bar_time"] == existing_valid["bar_time"] for row in plan["write"])
