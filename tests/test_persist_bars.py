from stock_pm.persist import PersistMixin


class _SpyPersist(PersistMixin):
    def __init__(self) -> None:
        self.pool_touched = False
        self.pool = self

    def connection(self):
        self.pool_touched = True
        raise AssertionError("quarantine without confirm must not touch the database")


def test_quarantine_without_confirm_does_not_delete():
    store = _SpyPersist()
    assert store.quarantine_invalid_daily_bars() == 0
    assert store.quarantine_invalid_daily_bars(confirm=False) == 0
    assert store.pool_touched is False
