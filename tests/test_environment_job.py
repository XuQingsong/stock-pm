from stock_pm.environment import failed_snapshot
from stock_pm.environment_job import publish_environment_snapshots


class MemoryStore:
    def __init__(self, *, fail_symbols=None, fail_append=None):
        self.fail_symbols = set(fail_symbols or [])
        self.fail_append = set(fail_append or [])
        self.snapshots: list[dict] = []
        self.jobs: list[dict] = []

    def market_session(self, trade_date=None):
        return {
            "date": trade_date or "2026-09-04",
            "is_trading_day": True,
            "default_review_date": "2026-09-04",
        }

    def active_symbols(self):
        return ["NVDA", "INTC"]

    def briefing(self, date=None):
        return {
            "date": date or "2026-09-04",
            "session": self.market_session(date),
            "rows": [{"symbol": "NVDA", "health": "趋势健康"}],
            "environment": {
                "as_of_date": date or "2026-09-04",
                "scope": "market",
                "one_liner": "市场半句",
                "publishState": "published",
                "missingFlags": [],
                "struct": {},
            },
        }

    def cboe_option_stats(self, trade_date=None):
        return {"trade_date": trade_date, "total_put_call": 0.8}

    def market_impact(self):
        return {"macro": []}

    def build_live_environment(self, symbol, as_of_date=None, **kwargs):
        if symbol in self.fail_symbols:
            raise RuntimeError("thesis exploded")
        return {
            "as_of_date": as_of_date,
            "scope": "symbol",
            "symbol": symbol,
            "one_liner": f"{symbol} 环境半句",
            "row_thesis": f"{symbol} 环境半句",
            "synthesis": f"{symbol} 环境半句",
            "struct": {"fundamentals": {"year_move": {"return_1y_pct": 10}}},
            "missingFlags": [],
            "publishState": "published",
            "prediction_ready": False,
        }

    def append_environment_snapshot(self, snapshot):
        symbol = snapshot.get("symbol") or snapshot.get("scope")
        if symbol in self.fail_append or snapshot.get("scope") in self.fail_append:
            raise RuntimeError("write failed")
        self.snapshots.append(snapshot)

    def append_job_run(self, job):
        self.jobs.append(job)


def test_publish_appends_market_and_each_symbol() -> None:
    store = MemoryStore()
    result = publish_environment_snapshots(store, as_of_date="2026-09-04")
    assert result["status"] == "success"
    scopes = [(row.get("scope"), row.get("symbol")) for row in store.snapshots]
    assert ("market", None) in scopes
    assert ("symbol", "NVDA") in scopes
    assert ("symbol", "INTC") in scopes
    assert store.jobs[-1]["job_name"] == "environment"
    assert store.jobs[-1]["status"] == "success"
    assert all(row.get("publishState") != "missing" for row in store.snapshots)


def test_publish_failure_writes_visible_missing_not_silence() -> None:
    store = MemoryStore(fail_symbols={"INTC"})
    result = publish_environment_snapshots(store, as_of_date="2026-09-04")
    assert result["status"] == "partial"
    intc = next(row for row in store.snapshots if row.get("symbol") == "INTC")
    assert intc["publishState"] == "missing"
    assert "未编造数字" in intc["one_liner"]
    assert intc["struct"]["fundamentals"] is None
    assert store.jobs[-1]["status"] == "partial"
    assert store.jobs[-1]["error"]
    assert "INTC" in store.jobs[-1]["error"]


def test_failed_snapshot_helper_matches_job_contract() -> None:
    snap = failed_snapshot("MU", "2026-09-04", "disk full")
    assert snap["missingFlags"]
    assert snap["struct"]["news"] == {"macro": None, "sector": None, "company": None}
